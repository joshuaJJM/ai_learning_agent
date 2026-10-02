"""Tutor 作答的重复提交保护（`answering_turn_id` 回显）。

背景：练习接口靠 `question_id` 天然分辨「网络重试」和「真的答下一题」，
Tutor 没有这个东西 —— 客户端只说「我选了 A」。于是同一份作答连发两次
会被当成两次作答，第二次还会消费掉下一轮，学生根本没看见那道题
就被记了一条 Evidence、掌握度也被动了一次。

修法与练习对称：客户端回显「我正在回答哪一轮」的 turn_id。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import db, repositories

KP = "math.derivative.monotonicity_applications"


def _create(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post(
        "/api/v1/tutor/sessions",
        headers=headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": KP},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _turns(session_id: str) -> int:
    return db.count_docs("tutor_turns", "tutor_session_id = ?", [session_id])


def _evidence(user_id: str) -> int:
    return db.count_docs("evidence", "user_id = ?", [user_id])


def _submit(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    key: str,
    *,
    answering_turn_id: str | None = None,
) -> Any:
    payload: dict[str, Any] = {"selected_key": key}
    if answering_turn_id:
        payload["answering_turn_id"] = answering_turn_id
    return client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns", headers=headers, json=payload
    )


# ---------------------------------------------------------------------------
# 带 turn_id 回显 → 正确去重
# ---------------------------------------------------------------------------

def test_repeating_the_same_turn_id_replays_instead_of_advancing(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]
    answered_turn = created["turn"]["turn_id"]

    before_turns = _turns(session_id)
    first = _submit(
        client, auth_headers, session_id, "A", answering_turn_id=answered_turn
    )
    assert first.status_code == 200, first.text
    assert first.json()["replayed"] is False
    after_first_turns = _turns(session_id)
    after_first_evidence = _evidence(demo_user["user_id"])
    assert after_first_turns > before_turns

    second = _submit(
        client, auth_headers, session_id, "A", answering_turn_id=answered_turn
    )
    assert second.status_code == 200, second.text
    assert second.json()["replayed"] is True

    # 关键：没有多追一轮，也没有多算一次
    assert _turns(session_id) == after_first_turns, "重放不该再追一条 turn"
    assert _evidence(demo_user["user_id"]) == after_first_evidence

    # 原样回放
    assert second.json() | {"replayed": False} == first.json()


def test_replay_does_not_consume_the_next_step(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """★ 核心：不带保护时会消费掉下一轮，带上之后必须停在原地。"""
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]
    answered_turn = created["turn"]["turn_id"]

    first = _submit(
        client, auth_headers, session_id, "A", answering_turn_id=answered_turn
    ).json()
    second = _submit(
        client, auth_headers, session_id, "A", answering_turn_id=answered_turn
    ).json()

    assert second["turn"]["turn_id"] == first["turn"]["turn_id"]
    assert second["turn"]["seq"] == first["turn"]["seq"]
    assert second["turn"]["turn_type"] == first["turn"]["turn_type"]
    assert second["turn"]["remedial_depth"] == first["turn"]["remedial_depth"]


def test_replay_works_for_the_last_turn_of_a_completed_session(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """顺序陷阱：重放检查必须排在 completed 检查之前。

    最后一轮答完时会话已经 completed，此时的重试应当拿到上次结果，
    而不是被判成「会话已结束」（409）。
    """
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]

    # 一路答到完成，记下最后一轮回答的是哪个 turn
    answering = created["turn"]["turn_id"]
    last_key = "A"
    for _ in range(20):
        body = _submit(
            client, auth_headers, session_id, last_key, answering_turn_id=answering
        ).json()
        if body["completed"]:
            break
        turns = client.get(
            f"/api/v1/tutor/sessions/{session_id}", headers=auth_headers
        ).json()
        answering = turns["turn"]["turn_id"]
        choices = turns["turn"].get("choices") or []
        last_key = choices[0]["key"] if choices else "A"

    state = client.get(
        f"/api/v1/tutor/sessions/{session_id}", headers=auth_headers
    ).json()
    assert state["completed"] is True, "需要先走到完成"

    # 重放最后一轮：必须是 200 回放，不是 409
    replay = _submit(
        client, auth_headers, session_id, last_key, answering_turn_id=answering
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True


# ---------------------------------------------------------------------------
# 不带 turn_id → 没有保护（记录现状，提醒客户端一定要带）
# ---------------------------------------------------------------------------

def test_without_turn_id_a_duplicate_is_still_treated_as_a_new_answer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """这是**已知且已文档化**的行为：不带回显就没有保护。

    保留这条测试是为了让「不带 turn_id 会怎样」有据可查，
    而不是让它在某次重构里悄悄变得更糟。
    """
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]

    first = _submit(client, auth_headers, session_id, "A").json()
    second = _submit(client, auth_headers, session_id, "A").json()

    assert second["replayed"] is False
    assert second["turn"]["seq"] != first["turn"]["seq"], (
        "不带 turn_id 时第二份作答会被当成对下一轮的回答 —— "
        "这正是前端必须回显 turn_id 的原因"
    )


def test_unknown_turn_id_is_not_treated_as_a_replay(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """客户端瞎传一个 turn_id 不该把正常作答吃掉。"""
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]

    body = _submit(
        client, auth_headers, session_id, "A", answering_turn_id="turn_不存在"
    ).json()
    assert body["replayed"] is False
    assert body["turn"]["seq"] >= 2


# ---------------------------------------------------------------------------
# 与幂等键共存
# ---------------------------------------------------------------------------

def test_turn_id_replay_and_idempotency_key_do_not_interfere(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]
    answered_turn = created["turn"]["turn_id"]

    response = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers={**auth_headers, "Idempotency-Key": "both-mechanisms"},
        json={"selected_key": "A", "answering_turn_id": answered_turn},
    )
    assert response.status_code == 200
    assert response.json()["replayed"] is False

    # 同 key 重放
    again = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers={**auth_headers, "Idempotency-Key": "both-mechanisms"},
        json={"selected_key": "A", "answering_turn_id": answered_turn},
    )
    assert again.status_code == 200
    assert again.json()["replayed"] is True
    assert again.json()["turn"]["turn_id"] == response.json()["turn"]["turn_id"]


def test_answered_turns_is_recorded_on_the_session(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """回放依据落在会话文档里，重连后仍然有效。"""
    created = _create(client, auth_headers)
    session_id = created["tutor_session_id"]
    answered_turn = created["turn"]["turn_id"]

    _submit(client, auth_headers, session_id, "A", answering_turn_id=answered_turn)

    session = repositories.get_tutor_session(session_id)
    assert session is not None
    assert answered_turn in (session.get("answered_turns") or {})
