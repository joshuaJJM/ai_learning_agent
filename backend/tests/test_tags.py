"""标签系统：计分规则与基于标签的推荐。

规则（按需求）：
  - 每个标签初始 0
  - 答对 → 该题所有标签 +1；答错 → -1
  - 推荐时把所有标签从小到大排序，返回包含分数最低标签的题目
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.question_bank import get_bank
from app.services import tag_service


def _scores(client: TestClient, headers: dict[str, str]) -> dict[str, int]:
    body = client.get("/api/v1/tags", headers=headers).json()
    return {item["tag"]: item["score"] for item in body["tags"]}


def _new_session(client: TestClient, headers: dict[str, str], count: int = 1) -> dict[str, Any]:
    response = client.post(
        "/api/v1/practice/sessions", headers=headers, json={"count": count}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _answer(
    client: TestClient, headers: dict[str, str], session_id: str, question_id: str, key: str
) -> dict[str, Any]:
    response = client.post(
        f"/api/v1/practice/sessions/{session_id}/answers",
        headers=headers,
        json={"question_id": question_id, "selected_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 计分
# ---------------------------------------------------------------------------

def test_all_tags_start_at_zero(client: TestClient) -> None:
    """「初始时给所有标签分配一个 0」——用全新用户验证，避免受其他测试影响。"""
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-fresh"}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    body = client.get("/api/v1/tags", headers=headers).json()

    assert body["tag_count"] > 0
    assert all(item["score"] == 0 for item in body["tags"])
    assert body["weakest"]["score"] == 0
    assert body["strongest"]["score"] == 0
    # 必须按分数升序返回
    values = [item["score"] for item in body["tags"]]
    assert values == sorted(values)


def test_wrong_answer_decrements_every_tag_of_the_question(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = _new_session(client, auth_headers)
    question_payload = session["next_question"]
    question = get_bank().get(question_payload["question_id"])
    assert question is not None and question.tags

    before = _scores(client, auth_headers)
    wrong_key = next(k for k in question.options if k != question.answer)
    result = _answer(
        client, auth_headers, session["practice_session_id"], question.id, wrong_key
    )

    assert result["is_correct"] is False
    assert result["tag_changes"]["delta"] == -1
    assert set(result["tag_changes"]["tags"]) == set(question.tags)

    after = _scores(client, auth_headers)
    for tag in question.tags:
        assert after[tag] == before[tag] - 1, tag


def test_correct_answer_increments_every_tag_of_the_question(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = _new_session(client, auth_headers)
    question_payload = session["next_question"]
    question = get_bank().get(question_payload["question_id"])
    assert question is not None and question.tags

    before = _scores(client, auth_headers)
    result = _answer(
        client,
        auth_headers,
        session["practice_session_id"],
        question.id,
        question.answer,
    )

    assert result["is_correct"] is True
    assert result["tag_changes"]["delta"] == 1

    after = _scores(client, auth_headers)
    for tag in question.tags:
        assert after[tag] == before[tag] + 1, tag


def test_homework_answer_also_moves_tags(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """上传批改这条链路同样要动标签。"""
    from .conftest import FIXTURE_IMAGE

    before = _scores(client, auth_headers)
    with FIXTURE_IMAGE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("page.png", handle, "image/png")},
            data={"subject": "mathematics"},
        )
    analysis_id = created.json()["analysis_id"]
    detail = client.get(
        f"/api/v1/homework/analyses/{analysis_id}", headers=auth_headers
    ).json()

    assert detail["status"] == "completed"
    after = _scores(client, auth_headers)
    # DEMO_QUESTION 是答错的 → 它的标签应当 -1
    tag = "利用导数判断函数单调性与单调区间"
    assert after[tag] == before[tag] - 1


# ---------------------------------------------------------------------------
# 推荐
# ---------------------------------------------------------------------------

def _user_id(demo_user: dict) -> str:
    return demo_user["user_id"]


def test_recommendation_returns_a_question_with_the_weakest_tag(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """人为把某个标签压到最低，推荐必须命中它。"""
    from app import repositories

    scores = _scores(client, auth_headers)
    target = sorted(scores.items(), key=lambda kv: kv[0])[0][0]

    # 把它压到严格低于当前最低分，避免受其他测试遗留的分数影响
    repositories.bump_tag_scores(
        _user_id(demo_user), [target], min(scores.values()) - 5
    )

    body = client.get("/api/v1/tags/recommend?count=1", headers=auth_headers).json()
    assert body["weakest"]["tag"] == target
    assert body["recommendations"], "应当推荐出题目"
    top = body["recommendations"][0]
    assert top["tag"] == target
    assert target in top["question_tags"]
    assert top["question"]["question_id"] == top["question_id"]
    # 下发的题目不能泄漏答案
    assert "answer" not in top["question"]
    assert "explanation" not in top["question"]


def test_tag_recommendation_is_deterministic(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    first = client.get("/api/v1/tags/recommend?count=3", headers=auth_headers).json()
    second = client.get("/api/v1/tags/recommend?count=3", headers=auth_headers).json()
    assert [r["question_id"] for r in first["recommendations"]] == [
        r["question_id"] for r in second["recommendations"]
    ]


def test_tag_recommendation_never_repeats_a_question(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = client.get("/api/v1/tags/recommend?count=8", headers=auth_headers).json()
    ids = [r["question_id"] for r in body["recommendations"]]
    assert len(ids) == len(set(ids))


def test_session_without_knowledge_point_uses_tag_selection(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = _new_session(client, auth_headers, count=3)
    assert session["selection_mode"] == "tag"
    assert session["target_tag"] is not None
    assert session["target_tag"] == session["picked_tags"][0]
    # 第一道题必须带目标标签
    assert session["target_tag"] in session["next_question"]["tags"]


def test_session_with_knowledge_point_keeps_old_behaviour(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/practice/sessions",
        headers=auth_headers,
        json={"knowledge_point_id": "math.derivative.monotonicity", "count": 2},
    )
    body = response.json()
    assert body["selection_mode"] == "knowledge_point"
    assert body["knowledge_point_id"] == "math.derivative.monotonicity"


def test_tag_selection_survives_a_fresh_user(client: TestClient) -> None:
    """全新用户所有标签都是 0，此时也要能选出题（不能因为全是 0 就空手而归）。"""
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-cold-start"}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    body = client.get("/api/v1/tags/recommend?count=3", headers=headers).json()
    assert len(body["recommendations"]) == 3
    assert all(r["tag_score"] == 0 for r in body["recommendations"])


# ---------------------------------------------------------------------------
# 标签表
# ---------------------------------------------------------------------------

def test_prompt_lists_every_tag() -> None:
    """VLM 提示词必须包含全部标签，否则模型没法从中挑。"""
    from app.services.vlm_service import build_prompt

    prompt = build_prompt()
    universe = tag_service.tag_universe()
    assert universe, "标签宇宙不能为空"
    for tag in universe:
        assert f"  - {tag}" in prompt, f"prompt 里缺少标签 {tag}"


def test_every_bank_question_has_tags() -> None:
    """题库每道题都要有标签，否则它永远不参与标签计分。"""
    bank = get_bank()
    missing = [q.id for q in bank.all() if not q.tags]
    assert not missing, f"这些题没有标签: {missing[:5]}"


# ---------------------------------------------------------------------------
# 清单一致性
# ---------------------------------------------------------------------------

def test_knowledge_list_matches_seed_file() -> None:
    """代码里的知识点清单必须与 seed/knowledge_points.json 一致。

    这条曾经静默出错：题库给了 17 个知识点，代码里只有 7 个，
    结果 46 道题挂不上知识点。现在启动会告警，测试也钉住。
    """
    from app import knowledge

    assert knowledge.validate_against_seed_file() == []


def test_tags_are_the_knowledge_point_names() -> None:
    """按 JSON标签与项目设计说明.txt：tags 是知识点 name 的展示层镜像。"""
    from app import knowledge

    universe = set(tag_service.tag_universe())
    names = {kp.name for kp in knowledge.all_points()}
    assert universe == names, f"多出来: {universe - names} / 缺少: {names - universe}"


def test_seed_file_declares_all_knowledge_points() -> None:
    import json

    from app import knowledge

    payload = json.loads(
        knowledge.seed_file_path().read_text(encoding="utf-8")
    )
    declared = {item["id"] for item in payload["knowledge_points"]}
    assert declared == {kp.id for kp in knowledge.all_points()}
    # 说明文档要求 version 2 收录全部 17 个
    assert payload["version"] >= 2
    assert len(declared) == 17
