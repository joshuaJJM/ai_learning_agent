"""代码评审 8 项问题的回归测试。

每条都对应一个具体的越权 / 数据污染 / 一致性缺陷，
修完必须有测试钉住，否则很容易再退回去。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import db, knowledge, repositories
from app.question_bank import get_bank

from .conftest import FIXTURE_IMAGE

DEMO_KP = "math.derivative.monotonicity_applications"


def _evidence_count(user_id: str) -> int:
    return db.count_docs("evidence", "user_id = ?", [user_id])


def _new_practice(client: TestClient, headers: dict[str, str], count: int = 1) -> dict[str, Any]:
    response = client.post(
        "/api/v1/practice/sessions", headers=headers, json={"count": count}
    )
    assert response.status_code == 201, response.text
    return response.json()


def _answer_question(client: TestClient, headers: dict[str, str]) -> tuple[dict[str, Any], Any]:
    """开一个单题练习，返回 (session, BankQuestion)。"""
    session = _new_practice(client, headers, count=1)
    question = get_bank().get(session["next_question"]["question_id"])
    assert question is not None
    return session, question


def _submit(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    question_id: str,
    key: str,
    client_request_id: str | None = None,
) -> Any:
    payload: dict[str, Any] = {"question_id": question_id, "selected_key": key}
    if client_request_id:
        payload["client_request_id"] = client_request_id
    return client.post(
        f"/api/v1/practice/sessions/{session_id}/answers", headers=headers, json=payload
    )


# ---------------------------------------------------------------------------
# P1-1 练习只能提交本 Session 的题
# ---------------------------------------------------------------------------

def test_practice_rejects_question_outside_the_session(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    session, current = _answer_question(client, auth_headers)

    outside = next(q.id for q in get_bank().all() if q.id != current.id)
    before = _evidence_count(demo_user["user_id"])

    response = _submit(client, auth_headers, session["practice_session_id"], outside, "A")

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "QUESTION_NOT_IN_SESSION"
    # 关键：被拒绝的提交不能写 Evidence
    assert _evidence_count(demo_user["user_id"]) == before


def test_practice_rejects_a_later_question_of_the_same_session(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """本组里还没轮到的那道题也不能提前提交。"""
    session = _new_practice(client, auth_headers, count=3)
    current = session["next_question"]["question_id"]

    # 直接造一条拿得到「本组第二题」的途径：用服务端会话记录
    stored = repositories.get_practice_session(session["practice_session_id"])
    assert stored is not None
    later = next(qid for qid in stored["question_ids"] if qid != current)

    before = _evidence_count(demo_user["user_id"])
    response = _submit(client, auth_headers, session["practice_session_id"], later, "A")

    assert response.status_code == 400, response.text
    assert response.json()["error_code"] == "QUESTION_NOT_IN_SESSION"
    assert _evidence_count(demo_user["user_id"]) == before


# ---------------------------------------------------------------------------
# P1-2 幂等：重试不重复记分
# ---------------------------------------------------------------------------

def test_practice_retry_does_not_double_count(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    session, question = _answer_question(client, auth_headers)

    first = _submit(
        client, auth_headers, session["practice_session_id"], question.id, question.answer
    )
    assert first.status_code == 200
    assert first.json()["replayed"] is False
    after_first = _evidence_count(demo_user["user_id"])

    second = _submit(
        client, auth_headers, session["practice_session_id"], question.id, question.answer
    )
    assert second.status_code == 200
    assert second.json()["replayed"] is True
    # 回放必须一字不差地返回上次结果，且不再写 Evidence
    assert second.json()["is_correct"] == first.json()["is_correct"]
    assert second.json()["knowledge_changes"] == first.json()["knowledge_changes"]
    assert _evidence_count(demo_user["user_id"]) == after_first


def test_practice_client_request_id_is_honoured(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """即使第一次的作答已被记下，同 request_id 也走幂等缓存。"""
    session, question = _answer_question(client, auth_headers)
    request_id = "retry-1"

    first = _submit(
        client, auth_headers, session["practice_session_id"], question.id,
        question.answer, client_request_id=request_id,
    )
    after_first = _evidence_count(demo_user["user_id"])
    second = _submit(
        client, auth_headers, session["practice_session_id"], question.id,
        question.answer, client_request_id=request_id,
    )
    assert second.status_code == 200
    # 命中幂等缓存同样是「回放」，必须标成 replayed；其余字段一字不差
    assert second.json()["replayed"] is True
    assert first.json()["replayed"] is False
    assert second.json() | {"replayed": False} == first.json()
    assert _evidence_count(demo_user["user_id"]) == after_first


def test_tutor_retry_does_not_double_count(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    ).json()
    session_id = created["tutor_session_id"]
    turn = created["turn"]
    assert turn["choices"], "首轮必须是选择题"

    payload = {
        "selected_key": turn["choices"][0]["key"],
        "client_request_id": "tutor-retry-1",
    }
    first = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns", headers=auth_headers, json=payload
    )
    assert first.status_code == 200, first.text
    after_first = _evidence_count(demo_user["user_id"])

    second = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns", headers=auth_headers, json=payload
    )
    assert second.status_code == 200
    # 重试会被明确标成 replayed；其余字段必须与首次完全一致
    assert second.json()["replayed"] is True
    assert first.json()["replayed"] is False
    assert second.json() | {"replayed": False} == first.json()
    assert _evidence_count(demo_user["user_id"]) == after_first


# ---------------------------------------------------------------------------
# P1-3 Tutor 不能回退到不存在的知识点
# ---------------------------------------------------------------------------

def test_tutor_never_falls_back_to_a_missing_knowledge_point(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": "math.derivative"},
    ).json()

    kp_id = created["knowledge_point_id"]
    assert knowledge.is_known(kp_id), f"{kp_id} 不在知识点清单里"
    assert kp_id != "math.derivative"


def test_tutor_without_knowledge_point_picks_a_real_one(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/api/v1/tutor/sessions", headers=auth_headers, json={"source_type": "knowledge_point"}
    ).json()
    assert knowledge.is_known(created["knowledge_point_id"])


def test_tutor_evidence_actually_moves_mastery(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """回归 P1-3 的直接后果：学完必须真的动掌握度。"""
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    ).json()
    session_id = created["tutor_session_id"]
    turn = created["turn"]

    # 故意答错，制造一个明确的 evidence
    wrong_key = next(
        c["key"] for c in turn["choices"] if c["key"] != turn.get("correct_key", "")
    )
    result = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers=auth_headers,
        json={"selected_key": wrong_key},
    ).json()
    assert result["knowledge_changes"], "Tutor 作答必须产生知识点变化"


# ---------------------------------------------------------------------------
# P1-4 序列号不能谎报另一本书兑换成功
# ---------------------------------------------------------------------------

def test_serial_cannot_claim_a_different_book(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    books = client.get("/api/v1/books", headers=auth_headers).json()["items"]
    owned = {b["book_id"] for b in books if b.get("owned")}
    another = next((b for b in books if b["book_id"] not in owned), None)
    assert another is not None, "需要一本未拥有的书"

    serial = "HAOXUE-AAAA-BBBB-CCCC"
    first_book = "book.derivative.basic"

    first = client.post(
        f"/api/v1/books/{first_book}/redeem",
        headers=auth_headers,
        json={"serial_number": serial},
    )
    assert first.status_code == 200, first.text
    assert first.json()["entitled"] is True

    # 同一个序列号去兑另一本书：必须失败，而不是回「你已拥有」
    second = client.post(
        f"/api/v1/books/{another['book_id']}/redeem",
        headers=auth_headers,
        json={"serial_number": serial},
    )
    assert second.status_code == 400, second.text
    assert second.json()["error_code"] == "INVALID_SERIAL_NUMBER"

    # 而且那本书确实没有被授予
    fresh = client.get("/api/v1/books", headers=auth_headers).json()["items"]
    target = next(b for b in fresh if b["book_id"] == another["book_id"])
    assert target.get("owned") is False, "接口撒谎了：书其实没到手"


def test_serial_format_is_actually_enforced(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    for bogus in ("HAOXUE-", "HAOXUE-12345678901234567890", "HAOXUE-abc", "NOT-A-SERIAL"):
        response = client.post(
            "/api/v1/books/book.derivative.advanced/redeem",
            headers=auth_headers,
            json={"serial_number": bogus},
        )
        assert response.status_code == 400, f"{bogus} 不该通过校验"
        assert response.json()["error_code"] == "INVALID_SERIAL_NUMBER"


# ---------------------------------------------------------------------------
# P2-5 从错题建 Tutor 必须校验归属
# ---------------------------------------------------------------------------

def test_tutor_from_another_users_wrong_question_is_rejected(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    # 造一条属于别人的错题
    other_user = client.post(
        "/api/v1/auth/guest", json={"device_id": "someone-else"}
    ).json()
    foreign = {
        "wrong_question_id": "wq_foreign_probe",
        "user_id": other_user["user_id"],
        "question_id": "math.derivative.comprehensive.1bd577aaf5",
        "knowledge_point_id": "math.derivative.monotonicity",
        "status": "open",
        "question_number": "1",
        "question_content": "别人的错题",
        "created_at": "2026-10-02T00:00:00+00:00",
        "updated_at": "2026-10-02T00:00:00+00:00",
    }
    repositories.save_wrong_question(foreign)

    response = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "wrong_question", "wrong_question_id": "wq_foreign_probe"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error_code"] == "WRONG_QUESTION_NOT_FOUND"


# ---------------------------------------------------------------------------
# P2-6 「专练一个标签」就要整组出自那个标签
# ---------------------------------------------------------------------------

def test_tag_session_stays_on_one_tag(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    from app.question_bank import get_bank
    from app.services import tag_service

    # v2 起标签统计从 Evidence 派生，直接改 tag_scores 表不再有效 ——
    # 要真的把一个标签练差，只能靠**实际答错**。
    # 会话本身会挑最弱的标签，所以连错几轮之后，那个标签会一直是最弱的（自我强化）。
    for _ in range(4):
        session = client.post(
            "/api/v1/practice/sessions", headers=auth_headers, json={"count": 1}
        ).json()
        question = get_bank().get(session["next_question"]["question_id"])
        assert question is not None
        wrong_key = next(k for k in question.options if k != question.answer)
        client.post(
            f"/api/v1/practice/sessions/{session['practice_session_id']}/answers",
            headers=auth_headers,
            json={"question_id": question.id, "selected_key": wrong_key},
        )

    scores = tag_service.scores(demo_user["user_id"])
    target = min(scores.items(), key=lambda kv: (kv[1], kv[0]))[0]

    body = client.get(
        "/api/v1/tags/recommend?count=5", headers=auth_headers
    ).json()

    assert body["recommendations"], "应当能推荐出题目"
    assert body["weakest"]["tag"] == target
    picked_tags = {r["tag"] for r in body["recommendations"]}
    assert picked_tags == {target}, f"5 道题应当都出自最弱标签，实际 {picked_tags}"
    for item in body["recommendations"]:
        assert target in item["question_tags"]


def test_tag_session_response_picked_tags_match_target(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    session = client.post(
        "/api/v1/practice/sessions", headers=auth_headers, json={"count": 3}
    ).json()
    assert session["selection_mode"] == "tag"
    assert session["picked_tags"][0] == session["target_tag"]


# ---------------------------------------------------------------------------
# P2-7 错题筛选必须在 SQL 里做
# ---------------------------------------------------------------------------

def test_wrong_question_book_filter_applies_before_limit(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """booking 筛选前的记录把 limit 占满时，仍要能筛出目标图书的错题。"""
    user_id = demo_user["user_id"]
    # 先塞一批「别的书」的错题（时间更新，会排在前面）
    for index in range(6):
        repositories.save_wrong_question(
            {
                "wrong_question_id": f"wq_noise_{index}",
                "user_id": user_id,
                "question_id": f"noise_{index}",
                "knowledge_point_id": "math.derivative.monotonicity",
                "book_id": "book.derivative.basic",
                "status": "open",
                "question_number": str(index),
                "created_at": f"2026-10-02T10:0{index}:00+00:00",
                "updated_at": f"2026-10-02T10:0{index}:00+00:00",
            }
        )
    # 再塞一条目标图书的错题，时间更早
    repositories.save_wrong_question(
        {
            "wrong_question_id": "wq_target_book",
            "user_id": user_id,
            "question_id": "target_1",
            "knowledge_point_id": "math.derivative.monotonicity",
            "book_id": "book.derivative.advanced",
            "status": "open",
            "question_number": "1",
            "created_at": "2026-10-01T00:00:00+00:00",
            "updated_at": "2026-10-01T00:00:00+00:00",
        }
    )

    response = client.get(
        "/api/v1/wrong-questions?book_id=book.derivative.advanced&limit=3",
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    items = response.json().get("items", [])
    assert [i["wrong_question_id"] for i in items] == ["wq_target_book"], (
        "先 LIMIT 再在 Python 里过滤会把这条漏掉"
    )


# ---------------------------------------------------------------------------
# P2-8 批次号唯一
# ---------------------------------------------------------------------------

def test_batch_numbers_stay_unique_when_a_duplicate_is_forced(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict, fake_vlm: None
) -> None:
    """并发下 MAX+1 会算出同一个号，插入冲突必须自动换号重试。"""
    from app.services import homework_service

    user_id = demo_user["user_id"]
    existing = repositories.next_batch_number(user_id)

    doc = {
        "analysis_id": "ana_forced_duplicate",
        "user_id": user_id,
        # 故意用一个已经被占用的批次号
        "batch_number": max(1, existing - 1),
        "status": "queued",
        "progress": homework_service._progress(0, 0.02),
        "subject": "mathematics",
        "image_count": 1,
        "counts": {"correct": 0, "wrong": 0, "partial": 0, "unknown": 0},
        "created_at": "2026-10-02T00:00:00+00:00",
        "updated_at": "2026-10-02T00:00:00+00:00",
        "finished_at": None,
    }
    repositories.insert_analysis(doc)

    assert doc["batch_number"] == repositories.next_batch_number(user_id) - 1
    batches = repositories.list_analysis_batches(user_id, limit=50)
    numbers = [b.get("batch_number") for b in batches]
    assert len(numbers) == len(set(numbers)), f"批次号出现重复: {numbers}"


def test_batch_number_uploads_stay_unique(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    created = []
    for index in range(3):
        with FIXTURE_IMAGE.open("rb") as handle:
            response = client.post(
                "/api/v1/homework/analyses",
                headers=auth_headers,
                files={"images": (f"u{index}.png", handle, "image/png")},
                data={"subject": "mathematics"},
            )
        created.append(response.json()["batch_number"])
    assert len(created) == len(set(created))
    assert created == sorted(created)


# ---------------------------------------------------------------------------
# 复审追加：批次号回填不能和已分配的号撞车
# ---------------------------------------------------------------------------

def _insert_analysis_row(
    user_id: str, analysis_id: str, batch_number: int, created: str
) -> None:
    from app import db

    db.execute(
        "INSERT INTO analyses (analysis_id, user_id, status, batch_number, "
        "created_at, updated_at, doc) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            analysis_id,
            user_id,
            "completed",
            batch_number,
            created,
            created,
            '{"analysis_id": "%s"}' % analysis_id,
        ],
    )


def test_backfill_skips_numbers_already_taken(demo_user: dict) -> None:
    """混合历史：加列前的老记录是 0，加列后新上传的已经拿到 1、2……

    如果回填一律从 1 开始编号，就会和已存在的 1 撞车，唯一索引建不起来。
    """
    from app import db

    user_id = "user_mixed_history_probe"
    conn = db.get_conn()

    # 退回到「刚加完列、还没建唯一索引」的状态
    conn.execute("DROP INDEX IF EXISTS uk_analyses_batch")
    conn.commit()

    # 2 条已经分配过号的（1 和 2），3 条还是 0 的历史记录
    _insert_analysis_row(user_id, "ana_mix_new1", 1, "2026-10-02T10:00:00+00:00")
    _insert_analysis_row(user_id, "ana_mix_new2", 2, "2026-10-02T10:01:00+00:00")
    _insert_analysis_row(user_id, "ana_mix_old1", 0, "2026-10-01T08:00:00+00:00")
    _insert_analysis_row(user_id, "ana_mix_old2", 0, "2026-10-01T09:00:00+00:00")
    _insert_analysis_row(user_id, "ana_mix_old3", 0, "2026-10-01T10:00:00+00:00")

    # 这一步以前会因为 1 撞车而失败
    db.ensure_batch_uniqueness(conn)

    rows = db.query_all(
        "SELECT analysis_id, batch_number FROM analyses WHERE user_id = ? "
        "ORDER BY batch_number",
        [user_id],
    )
    numbers = [int(r["batch_number"]) for r in rows]

    assert len(numbers) == len(set(numbers)), f"批次号重复: {numbers}"
    # 已分配的 1、2 必须保持原样（不能重编号，否则前端显示的历史会变）
    assert numbers[:2] == [1, 2]
    # 三个 0 记录从 3 开始接着编
    assert numbers[2:] == [3, 4, 5]
    assert "uk_analyses_batch" in db._index_names(conn, "analyses")

    db.execute("DELETE FROM analyses WHERE user_id = ?", [user_id])


def test_backfill_is_idempotent_when_nothing_to_do(demo_user: dict) -> None:
    from app import db

    conn = db.get_conn()
    assert db._backfill_batch_numbers(conn) == 0
    db.ensure_batch_uniqueness(conn)
    db.ensure_batch_uniqueness(conn)  # 再调一次不该报错


# ---------------------------------------------------------------------------
# 复审追加：并发幂等（不是顺序重试）
# ---------------------------------------------------------------------------

def test_practice_in_flight_request_is_rejected_not_double_counted(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """模拟两个进程同时收到同一请求。

    第一个已经占位但还没干完，第二个必须拿到 409，而不是各写一次 Evidence。
    """
    session, question = _answer_question(client, auth_headers)
    user_id = demo_user["user_id"]
    key = "concurrent-probe"
    idem_key = f"practice:{user_id}:{session['practice_session_id']}:{key}"

    # 另一个「进程」占住了位（还没写响应）
    assert repositories.reserve_idempotency(idem_key, user_id, "probe") is True
    before = _evidence_count(user_id)

    response = _submit(
        client, auth_headers, session["practice_session_id"], question.id,
        question.answer, client_request_id=key,
    )

    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert _evidence_count(user_id) == before, "并发请求必须没有写 Evidence"


def test_practice_completed_reservation_replays(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """占位被填成真正的响应之后，后续请求回放缓存。"""
    user_id = demo_user["user_id"]
    idem_key = "practice:probe:completed"

    repositories.reserve_idempotency(idem_key, user_id, "probe")
    repositories.put_idempotent_response(
        idem_key, user_id, "probe", {"cached": True, "value": 42}
    )
    assert repositories.is_idempotency_pending(idem_key) is False
    assert repositories.get_idempotent_response(idem_key) == {
        "cached": True,
        "value": 42,
    }


def test_failed_request_releases_the_reservation(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """业务失败必须释放占位，否则客户端永远重试不了。"""
    session, current = _answer_question(client, auth_headers)
    user_id = demo_user["user_id"]
    key = "release-probe"
    idem_key = f"practice:{user_id}:{session['practice_session_id']}:{key}"

    outside = next(q.id for q in get_bank().all() if q.id != current.id)
    response = _submit(
        client, auth_headers, session["practice_session_id"], outside, "A",
        client_request_id=key,
    )
    assert response.status_code == 400
    assert repositories.is_idempotency_pending(idem_key) is False, "占位没被释放"


def test_tutor_in_flight_request_is_rejected(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    created = client.post(
        "/api/v1/tutor/sessions",
        headers=auth_headers,
        json={"source_type": "knowledge_point", "knowledge_point_id": DEMO_KP},
    ).json()
    session_id = created["tutor_session_id"]
    user_id = demo_user["user_id"]
    key = "tutor-concurrent-probe"
    idem_key = f"tutor:{user_id}:{session_id}:{key}"

    assert repositories.reserve_idempotency(idem_key, user_id, "probe") is True
    before = _evidence_count(user_id)

    response = client.post(
        f"/api/v1/tutor/sessions/{session_id}/turns",
        headers=auth_headers,
        json={
            "selected_key": created["turn"]["choices"][0]["key"],
            "client_request_id": key,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error_code"] == "IDEMPOTENCY_CONFLICT"
    assert _evidence_count(user_id) == before
