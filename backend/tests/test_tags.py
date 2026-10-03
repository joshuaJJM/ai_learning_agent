"""标签系统：统计模型与基于标签的推荐。

v2 的模型（v1 是 ±1 计数器，有「5 对 5 错」和「从没练过」都是 0 的死穴）：

    每个标签维护 Beta(α, β)，用与掌握度相同的权重（对错 × 难度 × 来源 × 时间衰减）
    从 Evidence 现算；对外给的 score = (后验均值 − 一个标准差) × 100。

所以**没练过的标签不是 0，而是 21**（先验 Beta(1,1) 的悲观下界）——
0 意味着"确信完全不会"，而我们只是"还不知道"。
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

def test_fresh_user_tags_are_at_the_prior(client: TestClient) -> None:
    """全新用户：每个标签都是先验的悲观下界，**不是 0**。

    0 会被读成「确信完全不会」，而我们其实只是"还不知道"。
    Beta(1,1) 均值 0.5、sd≈0.289 → priority≈0.211 → 21。
    """
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-fresh"}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    body = client.get("/api/v1/tags", headers=headers).json()

    assert body["tag_count"] > 0
    assert all(item["score"] == 21 for item in body["tags"]), [i["score"] for i in body["tags"]]
    assert all(item["attempts"] == 0 for item in body["tags"])
    assert all(item["mastery"] == 0.5 for item in body["tags"]), "先验均值应当是 0.5"
    assert all(item["confidence"] == 0 for item in body["tags"]), "没有证据就没有把握"
    # 必须按分数升序返回
    values = [item["score"] for item in body["tags"]]
    assert values == sorted(values)


def test_untouched_and_balanced_are_now_distinguishable() -> None:
    """★ v1 的死穴：这两个曾经都是 0。

    5 对 5 错 = 练过但没掌握，优先度应当**低于**从没练过的。
    """
    untouched = tag_service.TagStat("t")
    balanced = tag_service.TagStat("t", alpha=6.0, beta=6.0)   # 先验 1,1 + 5 对 5 错
    weak = tag_service.TagStat("t", alpha=3.0, beta=9.0)       # 2 对 8 错
    strong = tag_service.TagStat("t", alpha=10.0, beta=2.0)    # 9 对 1 错

    assert untouched.score == 21
    assert balanced.score == 36
    assert weak.score == 13
    assert strong.score == 73

    assert weak.priority < untouched.priority < balanced.priority < strong.priority, (
        "排序应当是：练得差的 → 没碰过的 → 平衡的 → 掌握好的"
    )


def test_attempts_and_confidence_grow_with_evidence() -> None:
    stat = tag_service.TagStat("t")
    assert stat.confidence == 0.0
    stat.alpha += 3.0
    stat.beta += 0.0
    stat.attempts = 1
    stat.total_weight = 3.0
    assert 0.0 < stat.confidence < 1.0
    assert stat.mastery > 0.5


def test_one_answer_counts_once_per_tag(client: TestClient) -> None:
    """★ 一道题答一次，每个标签只能记一次。

    一道题有 N 个知识点就有 N 条 Evidence。如果每条 Evidence 都去记
    「该题的全部标签」，一道 2 个知识点的题答一次，每个标签会被记 **2 次**。
    （这是上线后实测发现的：一次作答 attempts 直接变成 2。）

    现在的做法是**每条 Evidence 只记它自己那个知识点的标签**，
    因为标签与知识点一一对应，所以每题每标签恰好一次。
    """
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-count-once"}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    session = _new_session(client, headers)
    question = get_bank().get(session["next_question"]["question_id"])
    assert question is not None

    result = _answer(
        client,
        headers,
        session["practice_session_id"],
        question.id,
        question.answer,
    )
    tags_hit = result["tag_changes"]["tags"]
    assert tags_hit, "这道题应当有标签"

    body = client.get("/api/v1/tags", headers=headers).json()
    by_tag = {item["tag"]: item for item in body["tags"]}
    for tag in tags_hit:
        assert by_tag[tag]["attempts"] == 1, (
            f"{tag} 被记了 {by_tag[tag]['attempts']} 次，"
            f"但学生只答了一次（题目有 {len(question.knowledge_point_ids)} 个知识点）"
        )


def test_wrong_answer_lowers_every_tag_of_the_question(
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
    changes = result["tag_changes"]
    assert set(changes["tags"]) == set(question.tags)
    assert set(changes["tag_scores"]) == set(question.tags)

    after = _scores(client, auth_headers)
    for tag in question.tags:
        assert after[tag] < before[tag], f"{tag} 答错后分数没有下降"
        assert changes["tag_deltas"][tag] == after[tag] - before[tag]
        assert changes["tag_scores"][tag] == after[tag]


def test_correct_answer_raises_every_tag_of_the_question(
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
    after = _scores(client, auth_headers)
    for tag in question.tags:
        assert after[tag] > before[tag], f"{tag} 答对后分数没有上升"


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
    # DEMO_QUESTION 是答错的 → 它那个标签的分数应当下降
    tag = "利用导数判断函数单调性与单调区间"
    assert after[tag] < before[tag], "作业批改这条链路没有影响标签"


# ---------------------------------------------------------------------------
# 推荐
# ---------------------------------------------------------------------------

def _user_id(demo_user: dict) -> str:
    return demo_user["user_id"]


def test_recommendation_returns_a_question_with_the_weakest_tag(
    client: TestClient,
) -> None:
    """把一个标签**真的练差**（连错几道），推荐必须命中它。

    用**独立 guest**：整个 session 共用一个 DB，demo 用户的标签统计会被
    其他用例累积，拿它断言绝对名次必然失败（这已经是第四次踩同一个坑了）。
    """
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-weakest"}).json()
    auth_headers = {"Authorization": f"Bearer {guest['access_token']}"}

    # 会话会自己挑最弱的标签；连错几道，把它压到明显低于其他标签
    for _ in range(4):
        session = _new_session(client, auth_headers)
        question = get_bank().get(session["next_question"]["question_id"])
        wrong_key = next(k for k in question.options if k != question.answer)
        _answer(
            client,
            auth_headers,
            session["practice_session_id"],
            question.id,
            wrong_key,
        )

    weakest_now = min(
        _scores(client, auth_headers).items(), key=lambda kv: (kv[1], kv[0])
    )
    target = weakest_now[0]
    assert weakest_now[1] < 21, "连错几道之后，最弱标签应当低于先验下界"

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
    """全新用户所有标签都在先验上，此时也要能选出题（不能空手而归）。"""
    guest = client.post("/api/v1/auth/guest", json={"device_id": "tag-cold-start"}).json()
    headers = {"Authorization": f"Bearer {guest['access_token']}"}

    body = client.get("/api/v1/tags/recommend?count=3", headers=headers).json()
    assert len(body["recommendations"]) == 3
    assert all(r["tag_score"] == 21 for r in body["recommendations"])


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
