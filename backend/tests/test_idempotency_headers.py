"""幂等键的两种传法都必须生效。

契约 §「幂等（重要）」写的是：

    - 推荐：任意请求带 `Idempotency-Key: <uuid>` 请求头
    - 或：请求体/表单里带 `client_request_id`

但一开始只有 homework 真的读了这个头，practice / tutor 只看请求体 ——
客户端照文档只发请求头的话，重试**拿不到承诺的保护**。
这个文件就是钉住「只发请求头也能幂等」。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import db, repositories
from app.question_bank import get_bank

DEMO_KP = "math.derivative.monotonicity_applications"


def _evidence_count(user_id: str) -> int:
    return db.count_docs("evidence", "user_id = ?", [user_id])


def _session_count(user_id: str) -> int:
    return db.count_docs("practice_sessions", "user_id = ?", [user_id])


def _tutor_session_count(user_id: str) -> int:
    return db.count_docs("tutor_sessions", "user_id = ?", [user_id])


# ---------------------------------------------------------------------------
# 请求体里的 client_request_id（原有能力，保证没退化）
# ---------------------------------------------------------------------------

def test_body_client_request_id_still_works(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
    ).json()
    question = get_bank().get(session["next_question"]["question_id"])
    assert question is not None

    payload = {
        "question_id": question.id,
        "selected_key": question.answer,
        "client_request_id": "body-key-1",
    }
    url = f"/api/v1/practice/sessions/{session['practice_session_id']}/answers"
    first = client.post(url, headers=auth_headers, json=payload)
    after_first = _evidence_count(demo_user["user_id"])
    second = client.post(url, headers=auth_headers, json=payload)

    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()
    assert _evidence_count(demo_user["user_id"]) == after_first


# ---------------------------------------------------------------------------
# 只用 Idempotency-Key 请求头（本次修复的重点）
# ---------------------------------------------------------------------------

def test_practice_answer_header_only_is_idempotent(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """客户端照文档只发请求头、请求体里没有 client_request_id。"""
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
    ).json()
    question = get_bank().get(session["next_question"]["question_id"])
    assert question is not None

    headers = {**auth_headers, "Idempotency-Key": "header-only-practice"}
    url = f"/api/v1/practice/sessions/{session['practice_session_id']}/answers"
    body = {"question_id": question.id, "selected_key": question.answer}

    first = client.post(url, headers=headers, json=body)
    assert first.status_code == 200, first.text
    after_first = _evidence_count(demo_user["user_id"])

    second = client.post(url, headers=headers, json=body)
    assert second.status_code == 200, second.text
    assert second.json() == first.json(), "只发请求头也必须回放"
    assert _evidence_count(demo_user["user_id"]) == after_first, "不能重复计分"


def test_practice_answer_accepts_x_idempotency_key_too(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
    ).json()
    question = get_bank().get(session["next_question"]["question_id"])
    assert question is not None

    headers = {**auth_headers, "X-Idempotency-Key": "x-header-practice"}
    url = f"/api/v1/practice/sessions/{session['practice_session_id']}/answers"
    body = {"question_id": question.id, "selected_key": question.answer}

    first = client.post(url, headers=headers, json=body)
    after_first = _evidence_count(demo_user["user_id"])
    second = client.post(url, headers=headers, json=body)

    assert second.json() == first.json()
    assert _evidence_count(demo_user["user_id"]) == after_first


def test_tutor_turn_header_only_is_idempotent(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    ).json()
    session_id = created["tutor_session_id"]
    choice = created["turn"]["choices"][0]["key"]

    headers = {**auth_headers, "Idempotency-Key": "header-only-tutor"}
    url = f"/api/v1/tutor/sessions/{session_id}/turns"

    first = client.post(url, headers=headers, json={"selected_key": choice})
    assert first.status_code == 200, first.text
    after_first = _evidence_count(demo_user["user_id"])

    second = client.post(url, headers=headers, json={"selected_key": choice})
    assert second.status_code == 200
    assert second.json() == first.json()
    assert _evidence_count(demo_user["user_id"]) == after_first


def test_practice_session_create_header_only_is_idempotent(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    headers = {**auth_headers, "Idempotency-Key": "header-only-practice-create"}
    before = _session_count(demo_user["user_id"])

    first = client.post("/api/v1/practice/sessions", headers=headers, json={"count": 3})
    second = client.post("/api/v1/practice/sessions", headers=headers, json={"count": 3})

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json(), "同一个 key 必须拿到同一个 Session"
    assert _session_count(demo_user["user_id"]) == before + 1, "不能多建一个 Session"


def test_tutor_session_create_header_only_is_idempotent(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    headers = {**auth_headers, "Idempotency-Key": "header-only-tutor-create"}
    body = {"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP}
    before = _tutor_session_count(demo_user["user_id"])

    first = client.post("/api/v1/tutor/sessions", headers=headers, json=body)
    second = client.post("/api/v1/tutor/sessions", headers=headers, json=body)

    assert first.status_code == second.status_code == 201
    assert second.json() == first.json()
    assert _tutor_session_count(demo_user["user_id"]) == before + 1


def test_books_redeem_header_only_is_idempotent(client: TestClient) -> None:
    """用独立访客，避免兑换行为污染其他用例的「未拥有图书」判断。"""
    guest = client.post("/api/v1/auth/guest", json={"device_id": "redeem-header"}).json()
    headers = {
        "Authorization": f"Bearer {guest['access_token']}",
        "Idempotency-Key": "header-only-redeem",
    }
    body = {"serial_number": "HAOXUE-DDDD-EEEE-FFFF"}
    url = "/api/v1/books/book.derivative.advanced/redeem"

    first = client.post(url, headers=headers, json=body)
    second = client.post(url, headers=headers, json=body)

    assert first.status_code == second.status_code == 200, first.text
    assert second.json() == first.json()
    assert second.json()["entitled"] is True


def test_header_and_body_keys_do_not_cross_contaminate(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """请求头优先；两者都带时以请求头为准，两个不同 key 各算一次。"""
    headers_a = {**auth_headers, "Idempotency-Key": "key-A"}
    headers_b = {**auth_headers, "Idempotency-Key": "key-B"}

    before = _session_count(demo_user["user_id"])
    client.post(
        "/api/v1/practice/sessions",
        headers=headers_a,
        json={"count": 1, "client_request_id": "body-ignored"},
    )
    client.post("/api/v1/practice/sessions", headers=headers_a, json={"count": 1})
    client.post("/api/v1/practice/sessions", headers=headers_b, json={"count": 1})

    # key-A 两次 → 一个 Session；key-B 一次 → 再一个
    assert _session_count(demo_user["user_id"]) == before + 2


def test_failed_redeem_releases_the_reservation(client: TestClient) -> None:
    guest = client.post("/api/v1/auth/guest", json={"device_id": "redeem-fail"}).json()
    headers = {
        "Authorization": f"Bearer {guest['access_token']}",
        "Idempotency-Key": "redeem-failure",
    }
    response = client.post(
        "/api/v1/books/book.derivative.advanced/redeem",
        headers=headers,
        json={"serial_number": "HAOXUE-"},
    )
    assert response.status_code == 400
    key = f"redeem:{guest['user_id']}:redeem-failure"
    assert repositories.is_idempotency_pending(key) is False, "失败必须释放占位"
