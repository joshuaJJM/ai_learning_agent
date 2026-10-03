"""人工确认/纠正标准答案（前端 Phase 8A Proposal）。

核心语义：
  - 只换标准答案，**题干 / 选项 / 知识点 / 标签 / 讲解全部沿用模型的产出**
  - 重新判定后**在本地重跑下游**（Evidence → 掌握度 / 标签 / 错题 / counts），不调 AI
  - 旧的 Evidence **删掉再写新的**，不是追加
  - 同一答案重复提交 → 回放，绝不重复写
  - 不同答案二次确认 → 409，不允许静默覆盖
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, repositories
from app.services import homework_service

from .conftest import FIXTURE_IMAGE

ENDPOINT = "/api/v1/homework/analyses/{aid}/questions/{qid}/confirm-answer"


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _upload(client: TestClient, headers: dict[str, str], name: str = "p.png") -> dict:
    with FIXTURE_IMAGE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=headers,
            files={"images": (name, handle, "image/png")},
            data={"subject": "mathematics", "source_name": name},
        )
    assert created.status_code == 202, created.text
    detail = client.get(
        f"/api/v1/homework/analyses/{created.json()['analysis_id']}", headers=headers
    ).json()
    assert detail["status"] == "completed", detail
    return detail


def _recount(doc: dict[str, Any]) -> None:
    counts = {"correct": 0, "wrong": 0, "partial": 0, "unanswered": 0, "unknown": 0}
    for item in doc["question_results"]:
        key = item.get("correctness", "unknown")
        counts[key] = counts.get(key, 0) + 1
    doc["counts"] = counts


def _force_unknown(analysis_id: str, *, student: str = "D", possible: str = "C") -> dict:
    """把第 1 题改成「复核没通过」的真实状态。

    假 VLM 只会产出确定判定，所以这里直接改存储 —— **包括删掉那条 Evidence**，
    因为 `unknown` 的题本来就不该有 Evidence。这样测的就是真实起点。
    """
    doc = repositories.get_analysis(analysis_id)
    question = doc["question_results"][0]
    repositories.delete_evidence_for_question(
        doc["user_id"], doc.get("homework_id") or "", question["question_id"]
    )
    question["correctness"] = "unknown"
    question["correct_answer"] = None
    question["possible_answer"] = possible
    question["possible_answer_source"] = "recognition"
    question["student_answer"] = student
    question["error_type"] = None
    _recount(doc)
    repositories.save_analysis(doc)
    repositories.save_question(question)
    return question


def _confirm(
    client: TestClient,
    headers: dict[str, str],
    analysis_id: str,
    question_id: str,
    answer: str,
    **extra: Any,
):
    return client.post(
        ENDPOINT.format(aid=analysis_id, qid=question_id),
        headers=headers,
        json={"correct_answer": answer, **extra},
    )


def _evidence_n(user_id: str, question_id: str) -> int:
    return len(
        db.query_all(
            "SELECT evidence_id FROM evidence WHERE user_id = ? AND question_id = ?",
            [user_id, question_id],
        )
    )


# ---------------------------------------------------------------------------
# Contract Drift 1：StageState 缺 retrying（这条本该早就有）
# ---------------------------------------------------------------------------

def test_every_progress_shape_satisfies_the_response_model() -> None:
    """★ 生产者产出的每一种 progress，响应模型都必须收得下。

    这条测试如果早点存在，就不会出现「`_progress` 会产出 `retrying`，
    但 `StageState` 里没有它 → 模型降级时 GET 直接 500」那个线上 bug。

    之前的测试只直接调了 `_progress()`，**没经过响应模型这个消费者** ——
    于是生产者对了、消费者挂了，测试全绿。
    """
    from app.schemas import AnalysisProgress

    produced = set()
    for active in range(len(homework_service.ANALYSIS_STAGES) + 1):
        for failed in (False, True):
            for retrying in (False, True):
                progress = homework_service._progress(
                    active,
                    0.5,
                    failed=failed,
                    retrying=retrying,
                    retry_note="换模型",
                )
                for stage in progress["stages"]:
                    produced.add(stage["state"])
                AnalysisProgress(**progress)  # 收不下就抛

    assert "retrying" in produced, "这条测试没覆盖到 retrying，等于白写"
    assert produced == {"done", "active", "retrying", "pending", "failed"}


def test_retrying_reaches_the_api_as_processing_not_failed(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """降级期间接口必须返回 retrying，且**不能**是 failed。"""
    detail = _upload(client, auth_headers)
    analysis_id = detail["analysis_id"]

    doc = repositories.get_analysis(analysis_id)
    doc["progress"] = homework_service._progress(
        1, 0.25, retrying=True, retry_note="第 1 张：deepseek-flash 未成功，正在重试（2/3）"
    )
    repositories.save_analysis(doc)

    body = client.get(f"/api/v1/homework/analyses/{analysis_id}", headers=auth_headers)
    assert body.status_code == 200, body.text
    progress = body.json()["progress"]
    assert progress["retrying"] is True
    assert "重试" in progress["retry_note"]
    assert [s["state"] for s in progress["stages"]].count("retrying") == 1


# ---------------------------------------------------------------------------
# 主流程：unknown → 人工确认
# ---------------------------------------------------------------------------

def test_confirm_unknown_writes_evidence_and_judges(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    """★ 学生答 D、标准答案确认为 C → 判错，并写入 Evidence。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"], student="D", possible="C")
    user_id = demo_user["user_id"]

    assert _evidence_n(user_id, question["question_id"]) == 0, "unknown 不该有 Evidence"

    response = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "C"
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["student_answer"] == "D"
    assert body["correct_answer"] == "C"
    assert body["correctness"] == "wrong"
    assert body["replayed"] is False
    assert body["confirmation"]["source"] == "user"
    assert body["confirmation"]["original_correct_answer"] == "C"  # AI 的猜测
    assert body["confirmation"]["correction_count"] == 1

    # Evidence 真的写进去了
    assert _evidence_n(user_id, question["question_id"]) > 0

    # counts 重算过：unknown 少 1、wrong 多 1
    summary = body["analysis_summary"]
    assert summary["unknown_count"] == 0
    assert summary["wrong_count"] == 1
    assert summary["question_count"] == 1

    # 判错 → 应当产生待复习项
    assert body["wrong_question"]["wrong_question_id"].startswith("wq_")
    assert body["wrong_question"]["status"] == "open"


def test_confirm_unknown_as_correct_does_not_create_wrong_question(
    client: TestClient, fake_vlm: None
) -> None:
    """判对之后不该有待复习项。

    用**独立 guest**：整个 session 共用一个 DB，而假 VLM 每次都返回同一道题，
    demo 用户的错题会跨用例累积，`wrong_question` 会被别的用例的历史污染。
    """
    guest = client.post(
        "/api/v1/auth/guest", json={"device_id": "confirm-correct"}
    ).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    detail = _upload(client, headers)
    question = _force_unknown(detail["analysis_id"], student="D", possible="C")

    body = _confirm(
        client, headers, detail["analysis_id"], question["question_id"], "D"
    ).json()

    assert body["correctness"] == "correct"
    assert body["analysis_summary"]["correct_count"] == 1
    assert body["wrong_question"] is None, "改判为答对之后不该还有待复习项"


def test_confirm_keeps_every_other_ai_field(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """★ 除了答案，模型的产出一个都不能丢。

    两边都从**数据库**取：接口响应里的 `QuestionResult` 只暴露了一部分字段，
    拿它跟库里比会误报"字段丢了"。
    """
    detail = _upload(client, auth_headers)
    question_id = detail["question_results"][0]["question_id"]
    before = repositories.get_question(question_id)
    assert before is not None

    question = _force_unknown(detail["analysis_id"])
    _confirm(client, auth_headers, detail["analysis_id"], question["question_id"], "C")

    after = repositories.get_question(question_id)
    assert after is not None
    for field in (
        "question_content",
        "choices",
        "knowledge_points",
        "tags",
        "difficulty",
        "explanation",
        "image_url",
        "question_number",
        "question_type",
    ):
        assert after[field] == before[field], f"{field} 被改动了，AI 的产出应当沿用"


# ---------------------------------------------------------------------------
# 幂等与重复确认
# ---------------------------------------------------------------------------

def test_same_answer_twice_replays_without_double_evidence(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    """★ 同一答案二次提交 → 回放，**不重复写 Evidence**。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])
    user_id = demo_user["user_id"]

    first = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "C"
    ).json()
    n_after_first = _evidence_n(user_id, question["question_id"])

    second = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "C"
    )
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True

    assert _evidence_n(user_id, question["question_id"]) == n_after_first, (
        "重复确认把 Evidence 写了两遍"
    )
    assert second.json()["analysis_summary"] == first["analysis_summary"]


def test_different_answer_after_confirmation_is_rejected(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """★ 不允许静默覆盖已确认的标准答案。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])

    _confirm(client, auth_headers, detail["analysis_id"], question["question_id"], "C")
    again = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "A"
    )

    assert again.status_code == 409, again.text
    assert again.json()["error_code"] == "QUESTION_ALREADY_RESOLVED"


def test_idempotency_key_replays(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])
    user_id = demo_user["user_id"]
    key = "confirm-idem-1"
    headers = {**auth_headers, "Idempotency-Key": key}

    first = client.post(
        ENDPOINT.format(aid=detail["analysis_id"], qid=question["question_id"]),
        headers=headers,
        json={"correct_answer": "C"},
    )
    assert first.status_code == 200, first.text
    n = _evidence_n(user_id, question["question_id"])

    second = client.post(
        ENDPOINT.format(aid=detail["analysis_id"], qid=question["question_id"]),
        headers=headers,
        json={"correct_answer": "C"},
    )
    assert second.status_code == 200
    assert _evidence_n(user_id, question["question_id"]) == n


def test_failed_confirmation_releases_the_idempotency_reservation(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """业务失败必须释放幂等占位，否则改个答案重试会被自己卡住。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])
    headers = {**auth_headers, "Idempotency-Key": "confirm-release-1"}
    url = ENDPOINT.format(aid=detail["analysis_id"], qid=question["question_id"])

    bad = client.post(url, headers=headers, json={"correct_answer": "Z"})
    assert bad.status_code == 400

    good = client.post(url, headers=headers, json={"correct_answer": "C"})
    assert good.status_code == 200, good.text


# ---------------------------------------------------------------------------
# 边界与错误
# ---------------------------------------------------------------------------

def test_unanswered_cannot_be_confirmed(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """学生没作答 → 补标准答案也判不出对错，必须拒绝。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])
    question["student_answer"] = None
    question["correctness"] = "unanswered"

    doc = repositories.get_analysis(detail["analysis_id"])
    doc["question_results"][0] = question
    _recount(doc)
    repositories.save_analysis(doc)
    repositories.save_question(question)

    response = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "C"
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "QUESTION_NOT_CONFIRMABLE"


def test_invalid_answer_is_rejected(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])

    response = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "Z"
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_ANSWER"


def test_unknown_question_is_not_found(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    detail = _upload(client, auth_headers)
    response = _confirm(
        client, auth_headers, detail["analysis_id"], "q_does_not_exist", "A"
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "QUESTION_NOT_FOUND"


def test_other_users_analysis_is_not_found(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])

    guest = client.post("/api/v1/auth/guest", json={"device_id": "confirm-other"}).json()
    other = {"Authorization": f"Bearer {guest['access_token']}"}

    response = _confirm(
        client, other, detail["analysis_id"], question["question_id"], "C"
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "ANALYSIS_NOT_FOUND"


def test_processing_analysis_cannot_be_confirmed(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    detail = _upload(client, auth_headers)
    question = detail["question_results"][0]

    doc = repositories.get_analysis(detail["analysis_id"])
    doc["status"] = "processing"
    repositories.save_analysis(doc)

    response = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], "A"
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "QUESTION_NOT_CONFIRMABLE"


# ---------------------------------------------------------------------------
# 超集：纠正一道**已经判定过**的题（用户要的"报错接口"）
# ---------------------------------------------------------------------------

def test_correcting_a_wrong_judgment_replaces_evidence(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    """★ 这就是「报错」的主场景：模型判错了，学生指出真正的答案。

    旧 Evidence 必须**被替换**而不是追加 —— 否则掌握度会同时算上
    "旧判定的错"和"新判定的对"，双重计数。
    """
    detail = _upload(client, auth_headers)
    question = repositories.get_question(detail["question_results"][0]["question_id"])
    assert question is not None and question["correctness"] == "wrong"

    user_id = demo_user["user_id"]
    qid = question["question_id"]
    n_before = _evidence_n(user_id, qid)
    assert n_before > 0, "判错的题本来就该有 Evidence"

    mastery_before = {
        ref["knowledge_point_id"]: client.get(
            f"/api/v1/knowledge/{ref['knowledge_point_id']}", headers=auth_headers
        ).json()["mastery"]
        for ref in question["knowledge_points"]
    }

    # 学生的作答其实就是对的（模型判错了）
    response = _confirm(
        client, auth_headers, detail["analysis_id"], qid, question["student_answer"]
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["correctness"] == "correct", "学生选的其实是对的，改判后不该还是错"

    # Evidence 被替换：条数不变（同题同知识点），没有翻倍
    assert _evidence_n(user_id, qid) == n_before, (
        f"Evidence 从 {n_before} 变成了 {_evidence_n(user_id, qid)} —— "
        f"应该是替换不是追加"
    )

    # 掌握度确实上升了
    for kp_id, before in mastery_before.items():
        after = client.get(
            f"/api/v1/knowledge/{kp_id}", headers=auth_headers
        ).json()["mastery"]
        assert after > before, f"{kp_id} 改判为答对后掌握度没有上升"

    # 判对了就不该再挂"错误类型"
    updated = repositories.get_question(qid)
    assert updated["error_type"] is None
    assert not updated["diagnosis"]


def test_correcting_to_wrong_creates_the_wrong_question(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """反向：模型认为对、学生指出正确答案 → 变成错题。"""
    detail = _upload(client, auth_headers)
    question = repositories.get_question(detail["question_results"][0]["question_id"])
    assert question is not None

    student = question["student_answer"]
    others = [k for k in question["choices"] if k != student]
    assert others, "需要有别的选项才能构造改判"

    body = _confirm(
        client, auth_headers, detail["analysis_id"], question["question_id"], others[0]
    ).json()

    assert body["correctness"] == "wrong"
    assert body["wrong_question"] is not None
    assert body["wrong_question"]["status"] == "open"


def test_confirmed_answer_shows_up_in_the_analysis_detail(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """确认之后，重新拉分析详情看到的必须是新判定。"""
    detail = _upload(client, auth_headers)
    question = _force_unknown(detail["analysis_id"])

    _confirm(client, auth_headers, detail["analysis_id"], question["question_id"], "D")

    fresh = client.get(
        f"/api/v1/homework/analyses/{detail['analysis_id']}", headers=auth_headers
    ).json()
    updated = next(
        q for q in fresh["question_results"] if q["question_id"] == question["question_id"]
    )
    assert updated["correctness"] == "correct"
    assert updated["correct_answer"] == "D"
    assert fresh["unknown_count"] == 0
    assert fresh["correct_count"] == 1
