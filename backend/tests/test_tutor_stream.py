"""Tutor 作答的流式返回。

契约：`POST /api/v1/tutor/sessions/{id}/turns`

  - `stream: false`（默认）→ 普通 JSON，**原有契约完全不变**
  - `stream: true`          → SSE：`meta` → `delta`×N → `turn` → `done`

`delta` 只承载自然语言（打字机效果），**不是权威数据**；
所有可交互 UI 数据都必须读最终的结构化 `turn` 事件。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

from app import repositories

DEMO_KP = "math.derivative.monotonicity_applications"


def _session(session_id: str) -> dict[str, Any]:
    session = repositories.get_tutor_session(session_id)
    assert session is not None
    return session


def _active_answer(session_id: str) -> str | None:
    session = _session(session_id)
    remedial = session.get("remedial")
    if remedial:
        return remedial["step"]["content"].get("answer")
    index = session["step_index"]
    plan = session["plan"]
    return plan[index]["content"].get("answer") if index < len(plan) else None


def _create(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    )
    assert created.status_code == 201, created.text
    return created.json()["tutor_session_id"]


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    """把 SSE 响应体解析成 [(event, payload), ...]。"""
    events: list[tuple[str, dict[str, Any]]] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        name = None
        data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = line[len("data: ") :]
        assert name is not None and data is not None, f"帧格式不对: {block!r}"
        events.append((name, json.loads(data)))
    return events


def _stream_answer(
    client: TestClient,
    headers: dict[str, str],
    sid: str,
    key: str,
    *,
    idem: str | None = None,
):
    extra = {"Idempotency-Key": idem} if idem else {}
    return client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers={**headers, **extra},
        json={"selected_key": key, "stream": True},
    )


# ---------------------------------------------------------------------------
# 事件序列
# ---------------------------------------------------------------------------

def test_stream_returns_sse_with_expected_event_order(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    response = _stream_answer(client, auth_headers, sid, _active_answer(sid) or "A")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # 前面若有 nginx，没有这个头流式会被攒起来一次性发出
    assert response.headers.get("x-accel-buffering") == "no"

    events = parse_sse(response.text)
    names = [name for name, _ in events]

    assert names[0] == "meta"
    assert names[-1] == "done"
    assert names.count("turn") == 1
    assert names.count("done") == 1
    assert "delta" in names
    # turn 必须在所有 delta 之后、done 之前
    turn_at = names.index("turn")
    assert all(
        name == "delta" for name in names[1:turn_at]
    ), f"turn 之前只应当是 delta：{names}"
    assert names.index("done") > turn_at


def test_meta_event_carries_session_identity(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    events = parse_sse(
        _stream_answer(client, auth_headers, sid, _active_answer(sid) or "A").text
    )
    meta = dict(events)["meta"]

    assert meta["tutor_session_id"] == sid
    assert meta["seq"] >= 1
    assert meta["phase"] in {
        "diagnose",
        "teach",
        "guided_practice",
        "independent_practice",
        "completed",
    }
    assert meta["turn_type"]
    assert "remedial_depth" in meta


def test_turn_event_is_authoritative_and_matches_the_json_contract(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """同一个作答，走流式与走 JSON，权威 turn 必须一致。

    做法：用两个等价 session，各答一次相同的题（同一个知识点、同一个索引），
    比对 turn 的结构字段。这里只比较与具体题目无关的字段，
    因为 bank 推荐可能给出不同的题。
    """
    sid = _create(client, auth_headers)
    text = _stream_answer(
        client, auth_headers, sid, _active_answer(sid) or "A"
    ).text
    events = dict(parse_sse(text))
    turn = events["turn"]

    # 结构化 UI 数据都在 turn 上，而不是从 delta 的自然语言里解析
    for field in (
        "turn_id",
        "seq",
        "turn_type",
        "text",
        "choices",
        "phase",
        "progress",
        "completed",
        "strategy",
        "remedial_depth",
        "answer_reveal",
    ):
        assert field in turn, f"turn 缺少 {field}"

    assert isinstance(turn["choices"], list)
    assert isinstance(turn["progress"], dict)
    # 选项必须是结构化的 key/text，而不是一段文字
    for choice in turn["choices"]:
        assert set(choice) == {"key", "text"}


def test_delta_accumulates_to_the_turn_text(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """delta 拼起来应当等于 turn.text（打字机效果，不改变内容）。"""
    sid = _create(client, auth_headers)
    events = parse_sse(
        _stream_answer(client, auth_headers, sid, _active_answer(sid) or "A").text
    )
    joined = "".join(payload["content"] for name, payload in events if name == "delta")
    turn = dict(events)["turn"]
    assert joined == turn["text"]


def test_done_event_carries_progress_and_completion(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    events = parse_sse(
        _stream_answer(client, auth_headers, sid, _active_answer(sid) or "A").text
    )
    done = dict(events)["done"]
    turn = dict(events)["turn"]

    assert done["seq"] == turn["seq"]
    assert done["completed"] == turn["completed"]
    assert done["progress"] == turn["progress"]
    assert 0.0 <= done["student_understanding"] <= 1.0


def test_stream_carries_remedial_depth_and_strategy(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """流式下补救信息同样完整，且不泄漏答案。"""
    sid = _create(client, auth_headers)
    answer = _active_answer(sid)
    wrong = next(k for k in "ABCD" if k != (answer or "A").upper())

    events = dict(parse_sse(_stream_answer(client, auth_headers, sid, wrong).text))
    turn = events["turn"]

    assert turn["turn_type"] == "simpler_question"
    assert turn["strategy"] == "simplify"
    assert turn["remedial_depth"] == 1
    assert turn["answer_reveal"] is None, "流式也不能提前泄漏答案"


# ---------------------------------------------------------------------------
# 向后兼容
# ---------------------------------------------------------------------------

def test_stream_false_keeps_the_json_contract(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    response = client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers=auth_headers,
        json={"selected_key": _active_answer(sid) or "A", "stream": False},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert "turn" in body and "evaluation" in body and "progress" in body


def test_omitting_stream_field_keeps_the_json_contract(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """不带 stream 字段 = 老客户端，行为必须一字不变。"""
    sid = _create(client, auth_headers)
    response = client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers=auth_headers,
        json={"selected_key": _active_answer(sid) or "A"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


# ---------------------------------------------------------------------------
# 错误与幂等
# ---------------------------------------------------------------------------

def test_unknown_session_returns_json_error_not_sse(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """校验在开流之前完成 —— 404 走正常 HTTP 状态码，而不是塞个 error 事件。"""
    response = _stream_answer(client, auth_headers, "tut_does_not_exist", "A")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["error_code"] == "SESSION_NOT_FOUND"
    assert body["request_id"]


def test_completed_session_returns_json_error_not_sse(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    # 一路答对走到完成
    for _ in range(20):
        state = client.get(
            f"/api/v1/tutor/sessions/{sid}", headers=auth_headers
        ).json()
        if state["completed"]:
            break
        answer = _active_answer(sid)
        if answer is None:
            break
        client.post(
            f"/api/v1/tutor/sessions/{sid}/turns",
            headers=auth_headers,
            json={"selected_key": answer},
        )

    response = _stream_answer(client, auth_headers, sid, "A")
    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["error_code"] == "SESSION_COMPLETED"


def test_stream_replay_is_idempotent(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """同一个 Idempotency-Key 重放：不重复追 turn，回放同一个结果。"""
    sid = _create(client, auth_headers)
    key = "stream-replay-1"
    answer = _active_answer(sid) or "A"

    first = parse_sse(_stream_answer(client, auth_headers, sid, answer, idem=key).text)
    after_first = len(_session(sid)["history"])
    second = parse_sse(
        _stream_answer(client, auth_headers, sid, answer, idem=key).text
    )

    assert dict(first)["turn"]["turn_id"] == dict(second)["turn"]["turn_id"]
    assert len(_session(sid)["history"]) == after_first, "重放不该再追一条 turn"
    # 重放也要是完整的 SSE 序列
    assert [n for n, _ in second][0] == "meta"
    assert [n for n, _ in second][-1] == "done"


def test_json_and_stream_share_the_idempotency_cache(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """先用 JSON 提交，再用同一个 key 走流式 —— 应当回放同一个 turn。"""
    sid = _create(client, auth_headers)
    key = "mixed-mode-1"
    answer = _active_answer(sid) or "A"

    first = client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers={**auth_headers, "Idempotency-Key": key},
        json={"selected_key": answer},
    ).json()
    history_after = len(_session(sid)["history"])

    events = dict(
        parse_sse(_stream_answer(client, auth_headers, sid, answer, idem=key).text)
    )
    assert events["turn"]["turn_id"] == first["turn"]["turn_id"]
    assert len(_session(sid)["history"]) == history_after
