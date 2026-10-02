"""端到端 Demo 流程测试。

走的就是现场演示那条链路：

    首页 → 上传作业 → 轮询分析 → 错题 → 知识详情(43%)
      → Tutor 故意答错 → Agent 降级 → 学会 → 独立练习正确
      → Mastery 上移 → 首页 Next Action 变化

VLM 被替换成确定性的假实现，所以这个测试不依赖网络和模型。
真实 VLM 链路由 tools/probe_models.py 单独验证。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.question_bank import get_bank
from app.services import vlm_service
from app.services.vlm_service import RawQuestion, VlmOutcome

from .conftest import FIXTURE_IMAGE

DEMO_KP = "math.derivative.monotonicity_applications"
DEMO_QUESTION = {
    "question_number": "17",
    "stem": "已知函数 f(x) = x^3 - 3x^2 + 2，求 f(x) 的单调递增区间。",
    "options": {
        "A": "(-inf, 0)",
        "B": "(0, 2)",
        "C": "(-inf, 0) 和 (2, +inf)",
        "D": "(2, +inf)",
    },
    "student_answer": "A",
    "correct_answer": "C",
    "correctness": "wrong",
    "knowledge_point_ids": ["math.derivative.monotonicity"],
    "error_type": "transformation",
    "diagnosis": "学生能正确求导，但把导数符号与单调性的对应关系弄反了。",
    "explanation": "f'(x)=3x^2-6x=3x(x-2)，f'(x)>0 得 x<0 或 x>2。",
    "confidence": 0.93,
    "difficulty": 0.5,
}


@pytest.fixture()
def fake_vlm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _analyze(images: Any, **kwargs: Any) -> VlmOutcome:
        outcome = VlmOutcome(generated_by="fake-vlm", model="fake")
        outcome.questions.append(RawQuestion(**DEMO_QUESTION))
        return outcome

    monkeypatch.setattr(vlm_service, "analyze_images", _analyze)


def _seed(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.post("/api/v1/demo/seed", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------

def test_health_and_root(client: TestClient) -> None:
    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["question_count"] == 73
    assert body["bank_count"] == 1
    assert body["llm_mode"] == "mock"  # 测试环境强制 Mock

    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["api_prefix"] == "/api/v1"


def test_guest_auth_issues_token(client: TestClient) -> None:
    response = client.post("/api/v1/auth/guest", json={"device_id": "pytest-device"})
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"].startswith("user_")
    assert body["access_token"].startswith("tok_")

    # token 必须真的能用
    home = client.get(
        "/api/v1/home", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert home.status_code == 200


def test_invalid_token_is_rejected_not_silently_downgraded(client: TestClient) -> None:
    response = client.get(
        "/api/v1/home", headers={"Authorization": "Bearer tok_not_real"}
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "UNAUTHORIZED"
    assert "request_id" in response.json()


# ---------------------------------------------------------------------------
# Demo 种子 → 43%
# ---------------------------------------------------------------------------

def test_demo_seed_puts_comprehensive_near_43_percent(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    result = _seed(client, auth_headers)
    mastery = result["mastery"][DEMO_KP]["mastery"]
    assert 0.40 <= mastery <= 0.47, f"综合应用掌握度应落在 43% 附近，实际 {mastery}"

    # 最基础的知识点要明显更强，否则知识树没有层次
    assert result["mastery"]["math.derivative.monotonicity"]["mastery"] > mastery + 0.2
    assert result["weakest"][0]["knowledge_point_id"] == DEMO_KP


def test_home_suggests_the_weakest_point(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed(client, auth_headers)
    home = client.get("/api/v1/home", headers=auth_headers).json()

    assert home["next_action"]["knowledge_point_id"] == DEMO_KP
    assert home["next_action"]["action"] == "start_tutor"
    assert home["weakest"]["knowledge_point_id"] == DEMO_KP
    assert home["wrong_question_count"] == 0
    assert home["stats"]["total_evidence"] == 103
    assert len(home["knowledge_summary"]) >= 3


# ---------------------------------------------------------------------------
# 作业分析流水线
# ---------------------------------------------------------------------------

def test_homework_analysis_creates_evidence_and_wrong_question(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    _seed(client, auth_headers)
    before = client.get(
        f"/api/v1/knowledge/math.derivative.monotonicity", headers=auth_headers
    ).json()

    with FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("q17.png", handle, "image/png")},
            data={"subject": "mathematics", "source_name": "某作业本第 32 页"},
        )
    assert response.status_code == 202, response.text
    analysis_id = response.json()["analysis_id"]

    detail = client.get(
        f"/api/v1/homework/analyses/{analysis_id}", headers=auth_headers
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "completed", body
    assert body["progress"]["percent"] == 1.0
    assert [s["state"] for s in body["progress"]["stages"]] == ["done"] * 5

    assert body["image_count"] == 1
    assert body["wrong_count"] == 1
    assert len(body["question_results"]) == 1

    question = body["question_results"][0]
    assert question["correctness"] == "wrong"
    assert question["student_answer"] == "A"
    assert question["correct_answer"] == "C"
    assert question["knowledge_points"][0]["knowledge_point_id"] == (
        "math.derivative.monotonicity"
    )
    assert body["questions"] == [question["question_id"]]

    # 掌握度必须真的被更新，且是可解释的
    assert body["knowledge_changes"], "分析完成后必须产生 knowledge_changes"
    change = body["knowledge_changes"][0]
    assert change["delta"] < 0, "答错应该让掌握度下降"

    # 错题自动入库
    assert len(body["new_wrong_questions"]) == 1
    wrong_id = body["new_wrong_questions"][0]["wrong_question_id"]

    wrong = client.get(f"/api/v1/wrong-questions/{wrong_id}", headers=auth_headers)
    assert wrong.status_code == 200
    wrong_body = wrong.json()
    assert wrong_body["correct_answer"] == "C"
    assert wrong_body["error_label"] == "函数性质转换错误"
    assert wrong_body["can_start_tutor"] is True
    assert wrong_body["image_url"]

    after = client.get(
        "/api/v1/knowledge/math.derivative.monotonicity", headers=auth_headers
    ).json()
    assert after["mastery"] < before["mastery"]
    assert after["evidence_count"] == before["evidence_count"] + 1


def test_analysis_is_idempotent_with_idempotency_key(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """网络重试不能把掌握度更新两次（契约 §22）。"""
    key = "retry-key-001"
    created = []
    for _ in range(2):
        with FIXTURE_IMAGE.open("rb") as handle:
            response = client.post(
                "/api/v1/homework/analyses",
                headers={**auth_headers, "Idempotency-Key": key},
                files={"images": ("q17.png", handle, "image/png")},
                data={"subject": "mathematics"},
            )
        assert response.status_code == 202
        created.append(response.json()["analysis_id"])
    assert created[0] == created[1]


def test_bad_image_is_rejected_with_error_code(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        files={"images": ("notes.png", b"this is definitely not an image", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_IMAGE"


def test_upload_accepts_octet_stream_without_extension(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """手工拼 multipart 的客户端（URLSession）默认发 octet-stream 且文件名没扩展名。

    以前这种请求会被拒（因为我们信了客户端声明的 content-type / 文件名），
    但图片本身是好的。现在只认文件头，所以应当接受。
    """
    data = FIXTURE_IMAGE.read_bytes()
    response = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        files={"images": ("photo", data, "application/octet-stream")},
    )
    assert response.status_code == 202, response.text


def test_upload_rejects_non_image_bytes_even_with_image_headers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """反过来也要成立：声明成 image/png 但字节不是图片，仍要拒绝。"""
    response = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        files={"images": ("fake.png", b"plain text pretending to be a png", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_IMAGE"


def test_upload_without_images_returns_invalid_image_not_validation_error(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """缺字段应当是明确的 INVALID_IMAGE，而不是含糊的 422。"""
    response = client.post(
        "/api/v1/homework/analyses",
        headers=auth_headers,
        data={"subject": "mathematics"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_IMAGE"


def test_unrecognized_question_fails_at_the_detection_stage(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """识别不出题目时，失败点必须落在 questions_detected 上。

    前端要靠这个在进度卡片上指出「就是这一步失败的」，
    所以这里的阶段状态必须是 failed 而不是 active。
    """

    async def _empty(images: Any, **kwargs: Any) -> VlmOutcome:
        return VlmOutcome(generated_by="fake-vlm", model="fake")  # 没有 questions

    monkeypatch.setattr(vlm_service, "analyze_images", _empty)

    with FIXTURE_IMAGE.open("rb") as handle:
        created = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("page.png", handle, "image/png")},
            data={"subject": "mathematics"},
        )
    analysis_id = created.json()["analysis_id"]
    body = client.get(
        f"/api/v1/homework/analyses/{analysis_id}", headers=auth_headers
    ).json()

    assert body["status"] == "failed"
    assert body["error"]["error_code"] == "QUESTION_NOT_RECOGNIZED"
    assert body["progress"]["current_stage_key"] == "questions_detected"

    states = {stage["key"]: stage["state"] for stage in body["progress"]["stages"]}
    assert states["image_received"] == "done"
    assert states["questions_detected"] == "failed"
    assert states["answers_understood"] == "pending"
    assert states["knowledge_updated"] == "pending"


def test_unknown_analysis_returns_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/homework/analyses/ana_missing", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error_code"] == "ANALYSIS_NOT_FOUND"


# ---------------------------------------------------------------------------
# Knowledge State
# ---------------------------------------------------------------------------

def test_knowledge_tree_is_returned_whole(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed(client, auth_headers)
    body = client.get("/api/v1/knowledge", headers=auth_headers).json()

    assert body["total_evidence"] == 103
    assert body["weakest"][0]["knowledge_point_id"] == DEMO_KP

    # 官方知识点清单是扁平的 7 个，全部作为顶层叶子节点返回
    node_ids = {node["knowledge_point_id"] for node in body["tree"]}
    assert len(node_ids) == 17
    assert "math.derivative.monotonicity_applications" in node_ids
    assert all(not node["children"] for node in body["tree"])

    # 有层次：最基础的那个最稳，综合应用最弱
    by_id = {node["knowledge_point_id"]: node for node in body["tree"]}
    assert (
        by_id["math.derivative.monotonicity_applications"]["mastery"]
        < by_id["math.derivative.monotonicity"]["mastery"]
    )


def test_knowledge_detail_explains_why(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """契约 §7：用户必须能看到"为什么是 43%"。"""
    _seed(client, auth_headers)
    body = client.get(f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers).json()

    assert body["name"] == "导数与函数性质综合应用"
    assert body["evidence_count"] == 12
    assert body["correct_count"] == 4
    assert body["partial_count"] == 3
    assert body["wrong_count"] == 5
    assert body["trend"] == "declining"

    assert len(body["error_patterns"]) >= 3
    top = body["error_patterns"][0]
    assert top["label"] == "分类讨论错误"
    assert top["count"] == 3

    assert len(body["evidence"]) == 12
    assert "掌握度为 43%" in body["mastery_explanation"]
    assert "分类讨论错误" in body["mastery_explanation"]
    assert body["prerequisites"][0]["knowledge_point_id"] == "math.derivative.monotonicity"
    assert body["recommended_action"]["knowledge_point_id"] == DEMO_KP


def test_unknown_knowledge_point_returns_error(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/knowledge/math.not_real", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error_code"] == "KNOWLEDGE_POINT_NOT_FOUND"


# ---------------------------------------------------------------------------
# Tutor Agent Loop
# ---------------------------------------------------------------------------

def _current_expected_answer(session_id: str) -> str | None:
    """白盒读取当前步骤的标准答案（客户端当然看不到，这是测试特权）。"""
    from app import repositories

    session = repositories.get_tutor_session(session_id)
    assert session is not None
    plan = session["plan"]
    index = session["step_index"]
    if index >= len(plan):
        return None
    return plan[index]["content"].get("answer")


def test_tutor_full_agent_loop(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed(client, auth_headers)
    before = client.get(f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers).json()

    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    )
    assert created.status_code == 201, created.text
    session = created.json()
    session_id = session["tutor_session_id"]

    assert session["phase"] == "diagnose"
    assert session["turn"]["turn_type"] == "concept_question"
    assert len(session["turn"]["choices"]) == 4
    assert session["completed"] is False

    # 1) 故意答错 → Agent 必须改变教学策略
    expected = _current_expected_answer(session_id)
    wrong_key = next(k for k in "ABCD" if k != expected)
    step = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers=auth_headers,
        json={"selected_key": wrong_key},
    ).json()

    assert step["evaluation"]["is_correct"] is False
    assert step["evaluation"]["strategy"] == "simplify"
    assert step["turn"]["turn_type"] == "simpler_question", "答错后必须换更简单的问题"

    # 2) 一路答对，直到完成
    guard = 0
    while not step["completed"] and guard < 20:
        guard += 1
        answer = _current_expected_answer(session_id)
        if answer is None:
            break
        step = client.post(
            f"/api/v1/tutor/sessions/{session_id}/turns",
            headers=auth_headers,
            json={"selected_key": answer},
        ).json()
        assert step["evaluation"]["is_correct"] is True

    assert step["completed"] is True, "Tutor 必须能走到完成"
    assert step["turn"]["turn_type"] == "summary"
    assert step["phase"] == "completed"
    assert step["progress"]["percent"] == 1.0
    assert step["next_action"] is not None, "完成后必须给出下一步建议"

    # 3) Mastery 必须真的变了（契约里 43% → 51% 的那一步）
    final = client.get(f"/api/v1/tutor/sessions/{session_id}", headers=auth_headers)
    assert final.status_code == 200
    assert final.json()["completed"] is True

    after = client.get(f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers).json()
    assert after["evidence_count"] > before["evidence_count"], "Tutor 必须产生 Evidence"
    assert after["mastery"] != before["mastery"]

    # 4) 完成的 Session 不能再作答
    again = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers=auth_headers,
        json={"selected_key": "A"},
    )
    assert again.status_code == 409
    assert again.json()["error_code"] == "SESSION_COMPLETED"


def test_tutor_from_wrong_question(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """三个入口之一：从错题进入 Tutor。"""
    _seed(client, auth_headers)
    with FIXTURE_IMAGE.open("rb") as handle:
        analysis = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("q17.png", handle, "image/png")},
            data={"subject": "mathematics"},
        ).json()
    detail = client.get(
        f"/api/v1/homework/analyses/{analysis['analysis_id']}", headers=auth_headers
    ).json()
    wrong_id = detail["new_wrong_questions"][0]["wrong_question_id"]

    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "wrong_question", "wrong_question_id": wrong_id},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["source_type"] == "wrong_question"
    assert body["knowledge_point_id"] == "math.derivative.monotonicity"
    assert "重新搞懂" in body["turn"]["text"]


# ---------------------------------------------------------------------------
# Practice
# ---------------------------------------------------------------------------

def test_practice_never_leaks_the_answer_but_still_updates_mastery(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed(client, auth_headers)
    created = client.post(
        "/api/v1/practice/sessions",
        headers=auth_headers,
        json={"knowledge_point_id": DEMO_KP, "count": 3},
    )
    assert created.status_code == 201, created.text
    session = created.json()
    session_id = session["practice_session_id"]
    assert session["next_question"] is not None

    # 契约 §14：不能把正确答案提前返回
    question = session["next_question"]
    assert "answer" not in question
    assert "explanation" not in question
    assert len(question["choices"]) == 4

    fetched = client.get(
        f"/api/v1/practice/sessions/{session_id}/next", headers=auth_headers
    ).json()
    assert "answer" not in fetched

    # 故意答错 → 判定、解析、掌握度更新
    correct = get_bank().get(question["question_id"]).answer
    wrong_key = next(k for k in "ABCD" if k != correct)

    before = client.get(f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers).json()
    result = client.post(
        f"/api/v1/practice/sessions/{session_id}/answers",
        headers=auth_headers,
        json={"question_id": question["question_id"], "selected_key": wrong_key},
    ).json()

    assert result["is_correct"] is False
    assert result["correct_answer"] == correct
    # 官方题库规范不含解析字段，所以 explanation 允许为 null
    assert result["explanation"] is None or result["explanation"]
    assert result["knowledge_changes"], "练习必须产生 Evidence 并更新掌握度"

    after = client.get(f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers).json()
    assert after["mastery"] < before["mastery"]


# ---------------------------------------------------------------------------
# 图书 / 权限 / AI
# ---------------------------------------------------------------------------

def test_books_and_redeem(client: TestClient, auth_headers: dict[str, str]) -> None:
    books = client.get("/api/v1/books", headers=auth_headers).json()
    assert books["total"] == 2
    first = next(b for b in books["items"] if b["book_id"] == "book.derivative.basic")
    assert first["owned"] is True  # Demo 默认赠送

    redeemed = client.post(
        "/api/v1/books/book.derivative.advanced/redeem",
        headers=auth_headers,
        json={"serial_number": "HAOXUE-ADVD-0002"},
    )
    assert redeemed.status_code == 200
    assert redeemed.json()["entitled"] is True

    entitlements = client.get("/api/v1/entitlements", headers=auth_headers).json()
    assert "book.derivative.advanced" in entitlements["owned_book_ids"]

    bad = client.post(
        "/api/v1/books/book.derivative.advanced/redeem",
        headers=auth_headers,
        json={"serial_number": "garbage"},
    )
    assert bad.status_code == 400
    assert bad.json()["error_code"] == "INVALID_SERIAL_NUMBER"


def test_ai_chat_simple_form(client: TestClient, auth_headers: dict[str, str]) -> None:
    """前端"跟踪训练"用的最简接口：发问题，拿回答。"""
    response = client.post(
        "/api/v1/ai/chat",
        headers=auth_headers,
        json={"prompt": "为什么 f'(x) > 0 说明函数单调递增？"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "mock"  # 测试环境强制 Mock
    assert body["reply"]
    assert body["model"]

    # 多轮形式
    multi = client.post(
        "/api/v1/ai/chat",
        headers=auth_headers,
        json={
            "system": "你是一位高中数学老师。",
            "messages": [
                {"role": "user", "content": "什么是导数？"},
                {"role": "assistant", "content": "导数描述变化率。"},
                {"role": "user", "content": "举个例子"},
            ],
        },
    )
    assert multi.status_code == 200

    empty = client.post("/api/v1/ai/chat", headers=auth_headers, json={})
    assert empty.status_code == 422
    assert empty.json()["error_code"] == "VALIDATION_ERROR"


def test_ai_models_lists_real_siliconflow_ids(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = client.get("/api/v1/ai/models", headers=auth_headers).json()
    assert body["default_model"]
    assert body["default_vision_model"]
    kinds = {m["kind"] for m in body["models"]}
    assert kinds == {"text", "vision"}


# ---------------------------------------------------------------------------
# 闭环
# ---------------------------------------------------------------------------

def test_full_demo_narrative(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """把 Demo Story 从头到尾走一遍，确认首尾能接上。"""
    _seed(client, auth_headers)

    home_before = client.get("/api/v1/home", headers=auth_headers).json()
    assert home_before["next_action"]["knowledge_point_id"] == DEMO_KP
    mastery_before = client.get(
        f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers
    ).json()["mastery"]

    # 扫描 → 分析 → 错题
    with FIXTURE_IMAGE.open("rb") as handle:
        analysis = client.post(
            "/api/v1/homework/analyses",
            headers=auth_headers,
            files={"images": ("q17.png", handle, "image/png")},
            data={"subject": "mathematics", "source_name": "数学月考"},
        ).json()
    detail = client.get(
        f"/api/v1/homework/analyses/{analysis['analysis_id']}", headers=auth_headers
    ).json()
    assert detail["status"] == "completed"

    # Tutor 学一轮
    session = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    ).json()
    session_id = session["tutor_session_id"]
    step = {"completed": False}
    guard = 0
    while not step.get("completed") and guard < 20:
        guard += 1
        answer = _current_expected_answer(session_id) or "A"
        step = client.post(
            f"/api/v1/tutor/sessions/{session_id}/turns",
            headers=auth_headers,
            json={"selected_key": answer},
        ).json()

    assert step["completed"] is True
    assert step["knowledge_changes"], "闭环的终点必须是 Mastery 变化"

    # 首页建议随之改变 / 至少不再是原来的理由
    home_after = client.get("/api/v1/home", headers=auth_headers).json()
    assert home_after["stats"]["total_evidence"] > home_before["stats"]["total_evidence"]

    mastery_after = client.get(
        f"/api/v1/knowledge/{DEMO_KP}", headers=auth_headers
    ).json()["mastery"]
    assert mastery_after != mastery_before

    activities = {a["activity_type"] for a in home_after["recent_activities"]}
    assert "homework" in activities
    assert "tutor" in activities
