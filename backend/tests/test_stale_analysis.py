"""终止态保证：分析不会永久停在 processing。

线上事故（前端 Phase 8B blocker）：分析跑在**进程内**的后台任务里，
服务一重启它就跟着死，而 analysis 记录停在 `processing` 永远不动。
实测 batch 5（ana_8996095d5cdc4942b9db）就是这样卡死的 ——
部署时杀掉旧进程，任务连同它的状态一起消失。

两道防线：
  1. 启动对账：进程刚起来不可能有任务在跑 → 遗留的非终态记录判失败
  2. 看门狗：进程活着但任务卡死 → 按 updated_at 超时判失败
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app import db, repositories
from app.services import homework_service

from .conftest import FIXTURE_IMAGE


def _guest(client: TestClient, device: str) -> tuple[dict[str, str], str]:
    """独立用户，返回 (headers, user_id)。

    两个坑都别再踩：
      - 不能用 demo 用户：批次号是「该用户内最大 +1」，助手造的高号会把
        水位抬起来，之后真实上传分配的号就会撞上
        （analyses 上有 unique(user_id, batch_number)）
      - **不能用 guest 的 headers 去调 `/auth/demo-user` 拿 id** ——
        那个接口返回的是 demo 用户，不是调用者，后面按这个 id 查数据就全错
    """
    response = client.post("/api/v1/auth/guest", json={"device_id": device})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def _make_analysis(
    user_id: str,
    *,
    status: str,
    age_seconds: int = 0,
    stage_state: str = "active",
) -> dict[str, Any]:
    """直接造一条分析记录（不用真跑一遍）。

    `batch_number` 用**真实的分配器**取 —— analyses 上有
    unique(user_id, batch_number)，自己编一个数迟早会撞上。
    """
    now = db.utcnow()
    stamp = db.to_iso(now - timedelta(seconds=age_seconds))
    doc = {
        "analysis_id": db.new_id("ana"),
        "user_id": user_id,
        "status": status,
        "batch_number": repositories.next_batch_number(user_id),
        "image_count": 1,
        "progress": homework_service._progress(1, 0.25, retrying=stage_state == "retrying"),
        "created_at": stamp,
        "updated_at": stamp,
    }
    doc["progress"]["stages"][1]["state"] = stage_state
    repositories.save_analysis(doc)
    return doc


def test_startup_recovery_fails_every_non_terminal_analysis(client: TestClient) -> None:
    """★ 服务刚起来时，遗留的 queued / processing 一定是孤儿。"""
    headers, uid = _guest(client, "stale-recover")
    processing = _make_analysis(uid, status="processing")
    queued = _make_analysis(uid, status="queued")
    done = _make_analysis(uid, status="completed")
    failed = _make_analysis(uid, status="failed")

    recovered = homework_service.recover_interrupted_analyses()
    assert recovered >= 2

    for doc in (processing, queued):
        after = repositories.get_analysis(doc["analysis_id"])
        assert after["status"] == "failed", f"{doc['status']} 没被收进终态"
        assert after["error"]["error_code"] == "ANALYSIS_INTERRUPTED"
        assert after["finished_at"], "判失败必须记完成时间"
        # 卡住的那一步要标成 failed，前端才知道死在哪
        states = [s["state"] for s in after["progress"]["stages"]]
        assert "failed" in states

    # 终态的不能被碰
    assert repositories.get_analysis(done["analysis_id"])["status"] == "completed"
    assert repositories.get_analysis(failed["analysis_id"])["status"] == "failed"


def test_recovery_is_idempotent(client: TestClient) -> None:
    """第二次跑不该再动任何东西（否则每次重启都重写一遍历史）。"""
    _, uid = _guest(client, "stale-idem")
    _make_analysis(uid, status="processing")
    assert homework_service.recover_interrupted_analyses() >= 1
    assert homework_service.recover_interrupted_analyses() == 0


def test_watchdog_reaps_only_stale_ones(client: TestClient) -> None:
    """★ 进程活着但任务卡死：只有**太久没动静**的才判失败。"""
    _, uid = _guest(client, "stale-watchdog")
    stale = _make_analysis(uid, status="processing", age_seconds=20 * 60)
    fresh = _make_analysis(uid, status="processing", age_seconds=30)

    reaped = homework_service.reap_stale_analyses()
    assert reaped >= 1

    after_stale = repositories.get_analysis(stale["analysis_id"])
    assert after_stale["status"] == "failed"
    assert after_stale["error"]["error_code"] == "ANALYSIS_TIMEOUT"

    after_fresh = repositories.get_analysis(fresh["analysis_id"])
    assert after_fresh["status"] == "processing", (
        "刚更新过的任务不能被看门狗误杀 —— 分析本来就要跑几分钟"
    )



def test_watchdog_threshold_is_longer_than_a_real_analysis() -> None:
    """阈值必须明显大于真实分析的耗时，否则会误杀正在跑的任务。

    实测最慢的一次（一页 9 题）用了 378 秒，阈值 15 分钟留了足够余量。
    """
    assert homework_service.STALE_ANALYSIS_SECONDS >= 600
    assert homework_service.STALE_ANALYSIS_SECONDS > 378 * 2


def test_reaper_cannot_clobber_an_analysis_that_finished_in_between(
    client: TestClient,
) -> None:
    """★ 最要命的那条：读完之后、写回之前，分析完成了。

    看门狗跑在另一个线程里，流程是「读一批 → 判断 → 写回整份 doc」。
    如果中间分析完成了，写回就等于把**已完成的结果覆盖成完成前的快照**：
    题目清空、homework_id 变 null、状态退回 failed —— 而 `questions` 与
    `evidence` 表里的数据还在，于是数据库看起来自相矛盾。

    线上真实事故：两条分析明明写入了 9 道题和 5 条 Evidence，
    analysis 文档却被改回「0 题 / failed / percent 0.25」。

    所以 `_fail_orphan` 必须**落笔前重读**，发现已进终态就跳过。
    """
    _, uid = _guest(client, "stale-race")
    doc = _make_analysis(uid, status="processing", age_seconds=3600)

    # ① 看门狗读到了这一份（此时它确实卡住了）
    stale_snapshot = repositories.get_analysis(doc["analysis_id"])
    assert stale_snapshot["status"] == "processing"

    # ② 在读出来之后、写回之前，分析完成了
    finished = repositories.get_analysis(doc["analysis_id"])
    finished["status"] = "completed"
    finished["homework_id"] = "hw_race"
    finished["question_results"] = [{"question_id": "q_race", "correctness": "correct"}]
    finished["counts"] = {"correct": 1}
    repositories.save_analysis(finished)

    # ③ 看门狗拿旧快照来收 —— 必须被挡住
    wrote = homework_service._fail_orphan(
        stale_snapshot, "ANALYSIS_TIMEOUT", "测试：不应覆盖"
    )
    assert wrote is False, "已进终态的分析不该被看门狗覆盖"

    after = repositories.get_analysis(doc["analysis_id"])
    assert after["status"] == "completed", "完成状态被覆盖了"
    assert after["homework_id"] == "hw_race", "homework_id 被打回 null 了"
    assert len(after["question_results"]) == 1, "题目结果被清空了"
    assert after.get("error") is None


def test_reaper_still_works_on_a_genuinely_stuck_one(client: TestClient) -> None:
    """加了防护之后，真正卡住的任务仍然要被收掉。"""
    _, uid = _guest(client, "stale-still-works")
    doc = _make_analysis(uid, status="processing", age_seconds=3600)

    wrote = homework_service._fail_orphan(
        doc, "ANALYSIS_TIMEOUT", "分析超过 15 分钟没有进展"
    )
    assert wrote is True
    after = repositories.get_analysis(doc["analysis_id"])
    assert after["status"] == "failed"
    assert after["error"]["error_code"] == "ANALYSIS_TIMEOUT"


def test_failed_by_recovery_can_be_retried(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """判失败之后前端要能直接重传 —— 不能因为状态卡住而拒绝新上传。"""
    detail = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        files={"images": ("p.png", FIXTURE_IMAGE.read_bytes(), "image/png")},
        data={"subject": "mathematics"},
    ).json()
    doc = repositories.get_analysis(detail["analysis_id"])
    if doc["status"] in ("queued", "processing"):
        homework_service._fail_orphan(
            doc, "ANALYSIS_INTERRUPTED", "模拟中断"
        )

    again = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        files={"images": ("p2.png", FIXTURE_IMAGE.read_bytes(), "image/png")},
        data={"subject": "mathematics"},
    )
    assert again.status_code == 202, again.text


def test_batch_list_shows_the_failure_not_a_stuck_processing(
    client: TestClient,
) -> None:
    """批列表里必须能看到 failed + 原因，而不是一直"处理中"。"""
    headers, uid = _guest(client, "stale-batches")
    doc = _make_analysis(uid, status="processing", age_seconds=3600)
    homework_service.reap_stale_analyses()

    body = client.get("/api/v1/homework/batches?limit=50", headers=headers).json()
    found = next(
        (
            b
            for b in (body.get("batches") or body.get("items") or [])
            if b.get("analysis_id") == doc["analysis_id"]
        ),
        None,
    )
    assert found is not None, "这条分析应当出现在批次列表里"
    assert found["state"] == "failed"
    assert found.get("error", {}).get("error_code") == "ANALYSIS_TIMEOUT"
