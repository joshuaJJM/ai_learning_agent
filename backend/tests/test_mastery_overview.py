"""综合掌握度接口 `GET /api/v1/knowledge/mastery-overview`。

这个数字是要给学生看的大标题，所以最怕的是**虚高** ——
只做了几道题却显示「掌握度 68%」。这组测试主要就是钉住这一点。

⚠️ 测试隔离：整个 session 共用一个数据库，而 `auth_headers`（demo 用户）
会被其它测试文件灌数据。所以凡是对「初始状态」有断言的用例，
一律用**独立 guest 用户**，不要用 demo 用户。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app import knowledge
from app.question_bank import get_bank

OVERVIEW = "/api/v1/knowledge/mastery-overview"


def _guest(client: TestClient, device: str) -> dict[str, str]:
    """建一个全新用户，返回它的请求头。device_id 决定身份，所以每个用例要用不同值。"""
    response = client.post("/api/v1/auth/guest", json={"device_id": device})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _overview(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.get(OVERVIEW, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _answer_one(client: TestClient, headers: dict[str, str], *, correct: bool) -> dict:
    """做一道题，返回那道题的信息。"""
    session = client.post(
        "/api/v1/practice/sessions", headers=headers, json={"count": 1}
    ).json()
    question = session["next_question"]
    answer = get_bank().get(question["question_id"]).answer
    chosen = answer if correct else next(k for k in "ABCD" if k != answer)
    client.post(
        f"/api/v1/practice/sessions/{session['practice_session_id']}/answers",
        headers=headers,
        json={"question_id": question["question_id"], "selected_key": chosen},
    )
    return question


# ---------------------------------------------------------------------------
# 基本契约
# ---------------------------------------------------------------------------

def test_cold_start_is_zero(client: TestClient) -> None:
    """什么都没做就是 0，不是 50，也不是 100。"""
    body = _overview(client, _guest(client, "mo-cold"))
    assert body["score"] == 0
    assert body["coverage"] == 0.0
    assert body["covered_count"] == 0
    assert body["evidence_count"] == 0
    assert body["weakest"] == []


def test_score_is_a_two_digit_integer(client: TestClient, auth_headers: dict) -> None:
    body = _overview(client, auth_headers)
    assert isinstance(body["score"], int)
    assert 0 <= body["score"] <= 99, "契约：两位数"


def test_response_exposes_the_full_breakdown(
    client: TestClient, auth_headers: dict
) -> None:
    body = _overview(client, auth_headers)
    for field in (
        "score",
        "percent",
        "weighted_mastery",
        "coverage",
        "covered_count",
        "point_count",
        "evidence_count",
        "weakest",
    ):
        assert field in body, f"缺少 {field}"

    assert body["point_count"] == len(knowledge.all_points())
    # 标签与知识点一一对应，所以这个数也等于标签总数
    assert body["point_count"] == 17
    assert 0.0 <= body["coverage"] <= 1.0
    assert 0.0 <= body["weighted_mastery"] <= 1.0
    assert len(body["weakest"]) <= 3


def test_is_read_only(client: TestClient, auth_headers: dict) -> None:
    """只读接口：连续调用两次结果必须一样。"""
    assert _overview(client, auth_headers) == _overview(client, auth_headers)


# ---------------------------------------------------------------------------
# 不虚高（这是这个算法存在的理由）
# ---------------------------------------------------------------------------

def test_one_correct_answer_does_not_inflate_the_score(client: TestClient) -> None:
    """只答对一道题时，加权平均可能到 0.6+，但覆盖率折算必须把它压住。"""
    headers = _guest(client, "mo-one-right")
    question = _answer_one(client, headers, correct=True)

    body = _overview(client, headers)
    # 一道题可能同时挂多个知识点，所以按题目的实际挂载数断言
    assert body["covered_count"] == len(question["knowledge_points"])
    assert body["weighted_mastery"] > 0.5, "单题答对，加权掌握度本身是高的"
    assert body["coverage"] < 0.3
    assert body["score"] <= 20, (
        f"只练了 {body['covered_count']}/{body['point_count']} 却给出 "
        f"{body['score']}，虚高了"
    )


def test_score_equals_weighted_mastery_times_coverage(client: TestClient) -> None:
    """把公式钉死，防止以后有人改算法却没意识到影响。"""
    headers = _guest(client, "mo-formula")
    _answer_one(client, headers, correct=False)

    body = _overview(client, headers)
    expected = round(body["weighted_mastery"] * body["coverage"] * 100)
    assert body["score"] == max(0, min(99, expected))


def test_wrong_answers_score_lower_than_right_ones(client: TestClient) -> None:
    """答错不能和答对一样 —— 掌握度得真的往下走。"""
    right = _overview(client, _guest(client, "mo-right"))["score"]
    headers_wrong = _guest(client, "mo-wrong")
    _answer_one(client, headers_wrong, correct=False)
    wrong = _overview(client, headers_wrong)["score"]

    headers_right = _guest(client, "mo-right-2")
    _answer_one(client, headers_right, correct=True)
    right = _overview(client, headers_right)["score"]

    assert right > wrong, f"答对 {right} 应当高于答错 {wrong}"


# ---------------------------------------------------------------------------
# demo 种子（用独立 guest，不碰共享的 demo 用户）
# ---------------------------------------------------------------------------

def test_demo_seed_produces_a_sensible_headline(client: TestClient) -> None:
    """铺完演示数据后应当是一个「有说服力但不夸张」的数字。"""
    headers = _guest(client, "mo-seeded")
    client.post("/api/v1/demo/seed", headers=headers)

    body = _overview(client, headers)
    assert body["coverage"] == 1.0, "种子数据应当覆盖全部知识点"
    assert body["evidence_count"] > 50
    assert 30 <= body["score"] <= 90, f"演示数字不合理：{body['score']}"

    # weakest 要能直接用来做「该练什么」
    assert len(body["weakest"]) == 3
    for item in body["weakest"]:
        assert item["name"]
        assert item["knowledge_point_id"] in {p.id for p in knowledge.all_points()}
    masteries = [item["mastery"] for item in body["weakest"]]
    assert masteries == sorted(masteries), "最弱的三个应当按掌握度升序"


def test_demo_seed_main_line_is_the_weakest(client: TestClient) -> None:
    """演示主线（43.2%）应当出现在最弱列表里。"""
    headers = _guest(client, "mo-seeded-main")
    client.post("/api/v1/demo/seed", headers=headers)
    body = _overview(client, headers)
    assert "math.derivative.monotonicity_applications" in {
        item["knowledge_point_id"] for item in body["weakest"]
    }


def test_demo_reset_brings_the_score_back_to_zero(client: TestClient) -> None:
    """重置后必须归零 —— 演示现场「重来一遍」要用。"""
    headers = _guest(client, "mo-reset")
    client.post("/api/v1/demo/seed", headers=headers)
    assert _overview(client, headers)["score"] > 0

    client.post("/api/v1/demo/reset", headers=headers)
    assert _overview(client, headers)["score"] == 0


# ---------------------------------------------------------------------------
# 路由顺序
# ---------------------------------------------------------------------------

def test_mastery_overview_is_not_swallowed_by_the_kp_route(
    client: TestClient, auth_headers: dict
) -> None:
    """`/{knowledge_point_id}` 是通配的，顺序错了这个接口就永远 404。"""
    response = client.get(OVERVIEW, headers=auth_headers)
    assert response.status_code == 200
    assert "score" in response.json()
    assert "error_code" not in response.json()


def test_real_knowledge_point_route_still_works(
    client: TestClient, auth_headers: dict
) -> None:
    ok = client.get(
        "/api/v1/knowledge/math.derivative.monotonicity", headers=auth_headers
    )
    assert ok.status_code == 200
    assert ok.json()["knowledge_point_id"] == "math.derivative.monotonicity"

    missing = client.get("/api/v1/knowledge/math.not_real", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error_code"] == "KNOWLEDGE_POINT_NOT_FOUND"
