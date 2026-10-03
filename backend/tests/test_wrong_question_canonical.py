"""错题的规范题目身份（前端 Phase 6 反馈）。

原来一行错题 = 「某次作业里的某道题」，同一道题在不同作业里做错
就各留一行，列表上看起来完全是重复的。

正确的模型：

    canonical question（题干指纹）
        └── attempts / evidence      ← 每次作答的完整历史，**永不删除**
                └── current wrong-question projection

一行错题 = **一道当前需要复习的规范题目**。多次做错合并进同一条，
`wrong_question_id` 从第一次起就固定不变。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import db, repositories
from app.services import wrong_question_service

from .conftest import FIXTURE_IMAGE


def _guest(client: TestClient, device: str) -> dict[str, str]:
    """独立用户。

    整个 session 共用一个 DB，而假 VLM 每次都返回**同一道题**，
    所以 demo 用户的错题会跨用例累积 —— 断言绝对次数必然失败。
    """
    response = client.post("/api/v1/auth/guest", json={"device_id": device})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _guest_user(client: TestClient, device: str) -> tuple[dict[str, str], str]:
    """同上，但把 user_id 一并返回（要按用户统计数据库行数时用）。"""
    response = client.post("/api/v1/auth/guest", json={"device_id": device})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def _upload(client: TestClient, headers: dict[str, str], name: str = "page.png") -> dict:
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


def _wrong_list(client: TestClient, headers: dict[str, str]) -> dict:
    return client.get("/api/v1/wrong-questions?limit=50", headers=headers).json()


# ---------------------------------------------------------------------------
# 同一道题做错两次 → 列表里只有一条
# ---------------------------------------------------------------------------

def test_same_question_wrong_twice_appears_once(
    client: TestClient, fake_vlm: None
) -> None:
    """★ 核心：两次作业里的同一道题，只应出现一个待复习项。"""
    auth_headers = _guest(client, "wq-once")
    before = _wrong_list(client, auth_headers)["total"]

    _upload(client, auth_headers, "第一次.png")
    after_first = _wrong_list(client, auth_headers)
    _upload(client, auth_headers, "第二次.png")
    after_second = _wrong_list(client, auth_headers)

    assert after_first["total"] == before + 1, "第一次应当新增一条错题"
    assert after_second["total"] == before + 1, (
        f"同一道题做错第二次不该新增错题项，实际 {before}→{after_second['total']}"
    )

    # 列表里没有重复题干
    stems = [item["question_content"] for item in after_second["items"]]
    assert len(stems) == len(set(stems)), f"列表里出现了重复题干：{stems}"


def test_wrong_question_id_is_stable_across_attempts(
    client: TestClient, fake_vlm: None
) -> None:
    """第一次做错时分配的 id 之后不再变 —— 前端可以安全地长期引用。"""
    auth_headers = _guest(client, "wq-stable")
    _upload(client, auth_headers, "A.png")
    first = {
        item["question_content"]: item
        for item in _wrong_list(client, auth_headers)["items"]
    }
    stem = next(iter(first))
    original_id = first[stem]["wrong_question_id"]

    _upload(client, auth_headers, "B.png")
    second = {
        item["question_content"]: item
        for item in _wrong_list(client, auth_headers)["items"]
    }
    assert second[stem]["wrong_question_id"] == original_id


def test_attempt_count_accumulates(client: TestClient, fake_vlm: None) -> None:
    auth_headers = _guest(client, "wq-count")
    _upload(client, auth_headers, "A.png")
    _upload(client, auth_headers, "B.png")
    _upload(client, auth_headers, "C.png")

    items = _wrong_list(client, auth_headers)["items"]
    target = max(items, key=lambda i: i["attempt_count"])
    assert target["attempt_count"] == 3, target
    assert target["first_wrong_at"] <= target["last_wrong_at"]
    assert target["question_stem_hash"], "应当带规范题目身份"


def test_detail_lists_every_attempt(client: TestClient, fake_vlm: None) -> None:
    """详情里能看到逐次作答 —— 「这道题我错过哪几次」。"""
    auth_headers = _guest(client, "wq-detail")
    _upload(client, auth_headers, "A.png")
    _upload(client, auth_headers, "B.png")

    items = _wrong_list(client, auth_headers)["items"]
    target = max(items, key=lambda i: i["attempt_count"])
    detail = client.get(
        f"/api/v1/wrong-questions/{target['wrong_question_id']}", headers=auth_headers
    ).json()

    assert detail["attempt_count"] == 2
    assert len(detail["attempts"]) == 2
    for attempt in detail["attempts"]:
        assert attempt["question_id"]
        assert attempt["homework_id"]
        assert attempt["created_at"]
    # 每次的 question_id 不同 —— 它们是不同的 attempt
    assert detail["attempts"][0]["question_id"] != detail["attempts"][1]["question_id"]


# ---------------------------------------------------------------------------
# 历史必须完整保留
# ---------------------------------------------------------------------------

def test_history_is_not_deleted(client: TestClient, fake_vlm: None) -> None:
    """★ 合并的是**错题投影**，不是历史。

    - `questions` 表：每次作业各一行（attempt 级），不能少
    - `evidence` 表：每次作答各一条，不能少
    """
    auth_headers, user_id = _guest_user(client, "wq-history")

    def counts() -> tuple[int, int]:
        return (
            db.count_docs("questions", "user_id = ?", [user_id]),
            db.count_docs("evidence", "user_id = ?", [user_id]),
        )

    q0, e0 = counts()
    _upload(client, auth_headers, "A.png")
    q1, e1 = counts()
    _upload(client, auth_headers, "B.png")
    q2, e2 = counts()

    assert q1 > q0, "第一次作业应当写入 question 记录"
    assert q2 > q1, "第二次作业**也**应当写入独立的 question 记录（attempt 历史）"
    assert e1 > e0 and e2 > e1, "每次作答都应当产生新的 Evidence"


def test_wrong_question_is_not_evidence(client: TestClient, fake_vlm: None) -> None:
    """错题条目的数量与 Evidence 的数量**本来就不该相等**。"""
    auth_headers, user_id = _guest_user(client, "wq-not-evidence")
    _upload(client, auth_headers, "A.png")
    _upload(client, auth_headers, "B.png")

    wrong_total = _wrong_list(client, auth_headers)["total"]
    evidence = db.count_docs("evidence", "user_id = ?", [user_id])
    assert evidence > wrong_total, "Evidence 是逐次累积的，错题是去重后的投影"


# ---------------------------------------------------------------------------
# 状态与合并规则
# ---------------------------------------------------------------------------

def test_erring_again_reopens_a_resolved_question(
    client: TestClient, fake_vlm: None
) -> None:
    """标记成已解决之后又做错了 → 必须重新变回待复习。

    否则学生会看到一道"已解决"的题其实是错的。
    """
    auth_headers = _guest(client, "wq-reopen")
    _upload(client, auth_headers, "A.png")
    items = _wrong_list(client, auth_headers)["items"]
    target = max(items, key=lambda i: i["attempt_count"])
    wid = target["wrong_question_id"]

    patched = client.patch(
        f"/api/v1/wrong-questions/{wid}", headers=auth_headers, json={"status": "resolved"}
    )
    assert patched.status_code == 200 and patched.json()["status"] == "resolved"

    _upload(client, auth_headers, "B.png")
    reopened = client.get(
        f"/api/v1/wrong-questions/{wid}", headers=auth_headers
    ).json()
    assert reopened["status"] == "open"
    assert reopened["attempt_count"] == 2


def test_record_attempt_merges_by_stem_hash() -> None:
    """直接调服务层，确认合并键是题干指纹而不是 question_id。"""
    user_id = "u_merge_test"
    snapshot: dict[str, Any] = {
        "question_id": "q_1",
        "question_number": "17",
        "question_content": "同一道题",
        "choices": {"A": "1", "B": "2"},
        "student_answer": "A",
        "correct_answer": "C",
        "correctness": "wrong",
        "source_type": "homework",
        "source_id": "hw_1",
    }

    first = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="hash-abc",
        snapshot=snapshot,
        attempt={"question_id": "q_1", "homework_id": "hw_1", "created_at": "t1"},
        now="2026-01-01T00:00:00+00:00",
    )
    second = wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="hash-abc",
        snapshot={**snapshot, "question_id": "q_2", "source_id": "hw_2"},
        attempt={"question_id": "q_2", "homework_id": "hw_2", "created_at": "t2"},
        now="2026-01-02T00:00:00+00:00",
    )

    assert second["wrong_question_id"] == first["wrong_question_id"]
    assert second["attempt_count"] == 2
    assert [a["question_id"] for a in second["attempts"]] == ["q_1", "q_2"]
    # 快照取最近一次
    assert second["question_id"] == "q_2"
    assert second["source_id"] == "hw_2"
    # 只应当有一条记录
    assert (
        len(repositories.list_wrong_questions(user_id, limit=10)) == 1
    ), "同一指纹不该产生第二行"


def test_different_questions_stay_separate() -> None:
    user_id = "u_separate_test"
    base: dict[str, Any] = {
        "question_id": "q",
        "question_number": "1",
        "question_content": "题干",
        "choices": {},
        "correctness": "wrong",
    }
    wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="hash-one",
        snapshot={**base, "question_content": "第一题"},
        attempt={"question_id": "q1"},
        now="2026-01-01T00:00:00+00:00",
    )
    wrong_question_service.record_attempt(
        user_id,
        question_stem_hash="hash-two",
        snapshot={**base, "question_content": "第二题"},
        attempt={"question_id": "q2"},
        now="2026-01-01T00:00:00+00:00",
    )
    assert len(repositories.list_wrong_questions(user_id, limit=10)) == 2


def test_attempts_list_is_capped() -> None:
    """明细有上限，但不能因为超限就丢计数。"""
    user_id = "u_cap_test"
    snapshot: dict[str, Any] = {
        "question_id": "q",
        "question_number": "1",
        "question_content": "题干",
        "choices": {},
        "correctness": "wrong",
    }
    total = wrong_question_service.MAX_KEPT_ATTEMPTS + 5
    for index in range(total):
        printed = wrong_question_service.record_attempt(
            user_id,
            question_stem_hash="hash-cap",
            snapshot={**snapshot, "question_id": f"q_{index}"},
            attempt={"question_id": f"q_{index}"},
            now=f"2026-01-01T00:{index:02d}:00+00:00",
        )

    assert len(printed["attempts"]) == wrong_question_service.MAX_KEPT_ATTEMPTS
    assert printed["attempt_count"] == total, "计数必须是真实的累计次数"
    assert len(repositories.list_wrong_questions(user_id, limit=10)) == 1


# ---------------------------------------------------------------------------
# demo seed / reset
# ---------------------------------------------------------------------------

def test_demo_seed_does_not_create_duplicate_wrong_questions(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """种子数据也不该制造重复错题。"""
    client.post("/api/v1/demo/seed", headers=auth_headers)
    body = _wrong_list(client, auth_headers)

    stems = [item["question_content"] for item in body["items"]]
    assert len(stems) == len(set(stems)), "种子数据产生了重复错题"

    hashes = [item["question_stem_hash"] for item in body["items"] if item["question_stem_hash"]]
    assert len(hashes) == len(set(hashes)), "同一规范题目被拆成了多条"
