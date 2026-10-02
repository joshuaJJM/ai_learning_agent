"""Tutor 补救（remedial）状态机。

规则（与前端 Phase 3B 约定一致）：

  - 正式题答错 → 进入补救，`remedial_depth` 从 1 开始
  - 最多 4 层，**不存在第 5 层**
  - 任意一层答对 → 结束补救，回到正常教学/下一正式题
  - 第 4 层仍答错 → 停止出题，返回正确答案 + 解析，允许进入下一题
  - 补救期间**绝不**下发表明正式题答案的字段

服务端是这些决定的唯一权威，客户端只负责呈现。
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app import repositories
from app.services import tutor_service

DEMO_KP = "math.derivative.monotonicity_applications"


# ---------------------------------------------------------------------------
# 白盒小工具（客户端看不到答案，测试才有这个特权）
# ---------------------------------------------------------------------------

def _session(session_id: str) -> dict[str, Any]:
    session = repositories.get_tutor_session(session_id)
    assert session is not None
    return session


def _active_answer(session_id: str) -> str | None:
    """当前该作答的那道题的标准答案 —— 补救优先。"""
    session = _session(session_id)
    remedial = session.get("remedial")
    if remedial:
        return remedial["step"]["content"].get("answer")
    index = session["step_index"]
    plan = session["plan"]
    if index >= len(plan):
        return None
    return plan[index]["content"].get("answer")


def _wrong_key(answer: str | None) -> str:
    assert answer, "当前步骤没有答案，测试构造失败"
    return next(k for k in "ABCD" if k != answer.upper())


def _create(client: TestClient, headers: dict[str, str]) -> str:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    )
    assert created.status_code == 201, created.text
    return created.json()["tutor_session_id"]


def _answer(client: TestClient, headers: dict[str, str], sid: str, key: str) -> dict:
    response = client.post(
        f"/api/v1/tutor/sessions/{sid}/turns",
        headers=headers,
        json={"selected_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 进入补救
# ---------------------------------------------------------------------------

def test_formal_question_wrong_enters_remedial_at_depth_one(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))

    assert body["evaluation"]["strategy"] == "simplify"
    assert body["turn"]["turn_type"] == "simpler_question"
    assert body["turn"]["remedial_depth"] == 1
    assert body["turn"]["strategy"] == "simplify"
    assert _session(sid)["remedial"]["depth"] == 1


def test_remedial_does_not_leak_the_formal_answer(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """补救进行中，turn 上不能出现任何答案字段。"""
    sid = _create(client, auth_headers)
    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))

    assert body["turn"]["answer_reveal"] is None, "补救第 1 层就泄漏答案是错的"
    assert body["evaluation"]["explanation"] is None
    # 原始 turn 里也不该夹带正解
    assert "answer" not in body["turn"]
    assert "correct_key" not in body["turn"]


# ---------------------------------------------------------------------------
# 逐层加深，最多 4 层
# ---------------------------------------------------------------------------

def test_remedial_never_exceeds_four_levels(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """一路答错：深度只会 1→2→3→4，然后必须停下来揭示答案。"""
    sid = _create(client, auth_headers)
    seen: list[int] = []
    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))
    seen.append(body["turn"]["remedial_depth"])

    for _ in range(8):  # 给足次数，逼出上限
        if body["turn"]["turn_type"] == "remedial_exhausted":
            break
        if body["turn"]["remedial_depth"] == 0:
            break
        answer = _active_answer(sid)
        if answer is None:
            break
        body = _answer(client, auth_headers, sid, _wrong_key(answer))
        seen.append(body["turn"]["remedial_depth"])

        assert body["turn"]["remedial_depth"] <= 4, f"出现了第 5 层：{seen}"

    assert seen[0] == 1, seen
    # 补救期间的深度必须是无缝递增的 1,2,3,4（末尾的 0 表示补救已结束）
    ladder = [d for d in seen if d > 0]
    assert ladder == list(range(1, len(ladder) + 1)), f"深度序列不连续：{seen}"
    assert max(ladder) <= 4, seen
    assert body["turn"]["turn_type"] == "remedial_exhausted", (
        f"一路答错必须停在上限并揭示答案，实际 {body['turn']}"
    )
    assert seen[-1] == 0, f"补救结束后深度应归零：{seen}"


def test_remedial_exhausted_reveals_answer_and_explanation(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    origin_answer = _active_answer(sid)
    body = _answer(client, auth_headers, sid, _wrong_key(origin_answer))

    for _ in range(8):
        if body["turn"]["turn_type"] == "remedial_exhausted":
            break
        answer = _active_answer(sid)
        if answer is None or body["turn"]["remedial_depth"] == 0:
            break
        body = _answer(client, auth_headers, sid, _wrong_key(answer))

    turn = body["turn"]
    assert turn["turn_type"] == "remedial_exhausted"
    assert body["evaluation"]["strategy"] == "reveal_answer"
    assert body["evaluation"]["remedial_exhausted"] is True

    reveal = turn["answer_reveal"]
    assert reveal is not None, "上限之后必须揭示答案"
    # 刚答错的那道补救题的答案
    assert reveal["current"]["correct_key"]
    # 触发补救的那道正式题的答案 —— 补救已结束，这时可以给
    assert reveal["origin"] is not None
    assert reveal["origin"]["correct_key"] == origin_answer

    # 揭示之后允许继续下一题：深度归零，且补救状态已清空
    assert turn["remedial_depth"] == 0
    assert _session(sid).get("remedial") is None


# ---------------------------------------------------------------------------
# 任意一层答对 → 结束补救
# ---------------------------------------------------------------------------

def test_correct_answer_ends_remedial_and_resumes_normal_flow(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    first_wrong = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))
    assert first_wrong["turn"]["remedial_depth"] == 1

    # 第 1 层补救答对
    body = _answer(client, auth_headers, sid, _active_answer(sid))

    assert body["evaluation"]["strategy"] == "advance"
    assert body["turn"]["remedial_depth"] == 0, "答对就要退出补救"
    assert _session(sid).get("remedial") is None
    assert body["turn"]["turn_type"] != "simpler_question", "不该还留在补救题上"
    # 答对了 → 可以给这道题的解析
    assert body["turn"]["answer_reveal"]["current"]["correct_key"]


def test_correct_at_deeper_level_also_ends_remedial(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """不是只有第 1 层答对才算 —— 任意一层都结束补救。"""
    sid = _create(client, auth_headers)
    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))

    # 先错到第 2 层（如果题库题不够，可能直接到上限，那就跳过）
    for _ in range(6):
        if body["turn"]["remedial_depth"] >= 2:
            break
        if body["turn"]["turn_type"] == "remedial_exhausted":
            return
        body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))

    if body["turn"]["remedial_depth"] < 2:
        return  # 这个知识点没有足够的补救题，跳过

    depth_before = body["turn"]["remedial_depth"]
    assert depth_before >= 2

    body = _answer(client, auth_headers, sid, _active_answer(sid))
    assert body["turn"]["remedial_depth"] == 0
    assert _session(sid).get("remedial") is None
    assert body["evaluation"]["strategy"] == "advance"


# ---------------------------------------------------------------------------
# 不破坏既有语义
# ---------------------------------------------------------------------------

def test_progress_ignores_remedial_steps(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """补救不计入进度 —— 学生不该因为被补救而降进度。"""
    sid = _create(client, auth_headers)
    before = client.get(
        f"/api/v1/tutor/sessions/{sid}", headers=auth_headers
    ).json()["turn"]["progress"]

    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))
    after = body["turn"]["progress"]

    assert after["step"] == before["step"], "补救期间进度不应前进"
    assert after["total_steps"] == before["total_steps"]


def test_strategy_values_are_from_the_declared_set(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    sid = _create(client, auth_headers)
    allowed = {"advance", "simplify", "hint", "re_explain", "reveal_answer", "finish"}
    body = _answer(client, auth_headers, sid, _wrong_key(_active_answer(sid)))
    assert body["evaluation"]["strategy"] in allowed
    assert body["turn"]["strategy"] in allowed


def test_max_remedial_depth_constant_is_four() -> None:
    assert tutor_service.MAX_REMEDIAL_DEPTH == 4
