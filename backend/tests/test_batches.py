"""上传批次：批次号分配与「近 50 批」列表。"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from .conftest import FIXTURE_IMAGE


def _upload(client: TestClient, headers: dict[str, str], name: str = "page.png") -> dict[str, Any]:
    with FIXTURE_IMAGE.open("rb") as handle:
        response = client.post(
            "/api/v1/homework/analyses",
            headers=headers,
            files={"images": (name, handle, "image/png")},
            data={"subject": "mathematics", "source_name": name},
        )
    assert response.status_code == 202, response.text
    return response.json()


def _batches(client: TestClient, headers: dict[str, str], limit: int = 50) -> dict[str, Any]:
    response = client.get(
        f"/api/v1/homework/batches?limit={limit}", headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# 批次号
# ---------------------------------------------------------------------------

def test_batch_number_increments_per_upload(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    """每上传一批就分配一个唯一且递增的批次号。"""
    first = _upload(client, auth_headers, "a.png")
    second = _upload(client, auth_headers, "b.png")

    assert isinstance(first["batch_number"], int)
    assert second["batch_number"] == first["batch_number"] + 1


def test_batch_number_is_unique_across_batches(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    numbers = [_upload(client, auth_headers, f"{i}.png")["batch_number"] for i in range(3)]
    assert len(numbers) == len(set(numbers))


def test_detail_carries_batch_number(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    created = _upload(client, auth_headers, "detail.png")
    detail = client.get(
        f"/api/v1/homework/analyses/{created['analysis_id']}", headers=auth_headers
    ).json()
    assert detail["batch_number"] == created["batch_number"]
    assert detail["finished_at"] is not None


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------

def test_batches_list_returns_recent_batches_newest_first(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    for i in range(3):
        _upload(client, auth_headers, f"list{i}.png")

    body = _batches(client, auth_headers, limit=50)

    assert body["total"] >= 3
    numbers = [item["batch_number"] for item in body["items"]]
    assert numbers == sorted(numbers, reverse=True), "最新的必须排在最前"
    assert len(body["items"]) <= body["limit"]


def test_successful_batch_has_finish_time_and_counts(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    _upload(client, auth_headers, "ok.png")
    body = _batches(client, auth_headers)
    item = body["items"][0]

    assert item["state"] == "success"
    assert item["state_label"] == "成功"
    assert item["finished_at"] is not None
    assert item["duration_seconds"] is not None and item["duration_seconds"] >= 0
    assert item["question_count"] == 1
    # DEMO_QUESTION 是答错的
    assert item["wrong_count"] == 1
    # 成功的不需要进度
    assert item["progress"] is None


def test_processing_batch_carries_the_same_progress_object(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    """进行中的批次必须带与详情接口完全一样的 progress。"""
    from app import repositories
    from app.services import homework_service

    # 直接造一条 processing 记录（TestClient 会同步跑完后台任务，
    # 没法在测试里自然观察到进行中的状态）
    doc = {
        "analysis_id": "ana_processing_probe",
        "user_id": demo_user["user_id"],
        "batch_number": 9999,
        "status": "processing",
        "progress": homework_service._progress(2, 0.62),
        "subject": "mathematics",
        "image_count": 1,
        "source_name": "进行中的批次",
        "counts": {"correct": 0, "wrong": 0, "partial": 0, "unknown": 0},
        "question_results": [],
        "created_at": "2026-10-02T00:00:00+00:00",
        "updated_at": "2026-10-02T00:00:01+00:00",
        "finished_at": None,
    }
    repositories.save_analysis(doc)

    body = _batches(client, auth_headers)
    item = next(i for i in body["items"] if i["analysis_id"] == "ana_processing_probe")

    assert item["state"] == "processing"
    assert item["state_label"] == "正在处理"
    assert item["progress"] is not None
    assert item["progress"]["current_stage_key"] == "answers_understood"
    keys = [s["key"] for s in item["progress"]["stages"]]
    assert keys == [
        "image_received",
        "questions_detected",
        "answers_understood",
        "error_patterns",
        "knowledge_updated",
    ]
    # 进行中不给完成时间
    assert item["finished_at"] is None
    assert item["duration_seconds"] is None


def test_failed_batch_carries_error_and_time(
    client: TestClient, auth_headers: dict[str, str], demo_user: dict
) -> None:
    from app import repositories
    from app.services import homework_service

    doc = {
        "analysis_id": "ana_failed_probe",
        "user_id": demo_user["user_id"],
        "batch_number": 9998,
        "status": "failed",
        "progress": homework_service._progress(1, 0.62, failed=True),
        "subject": "mathematics",
        "image_count": 1,
        "source_name": "失败的批次",
        "counts": {"correct": 0, "wrong": 0, "partial": 0, "unknown": 0},
        "question_results": [],
        "error": {
            "error_code": "QUESTION_NOT_RECOGNIZED",
            "message": "没有从图片中识别出题目",
        },
        "created_at": "2026-10-02T00:00:00+00:00",
        "updated_at": "2026-10-02T00:00:03+00:00",
        "finished_at": "2026-10-02T00:00:03+00:00",
    }
    repositories.save_analysis(doc)

    body = _batches(client, auth_headers)
    item = next(i for i in body["items"] if i["analysis_id"] == "ana_failed_probe")

    assert item["state"] == "failed"
    assert item["state_label"] == "失败"
    assert item["error"]["error_code"] == "QUESTION_NOT_RECOGNIZED"
    assert item["finished_at"] is not None
    assert item["duration_seconds"] == 3.0


def test_batches_counts_cover_all_states(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    _upload(client, auth_headers, "counts.png")
    body = _batches(client, auth_headers)

    assert body["processing_count"] + body["success_count"] + body["failed_count"] == body["total"]


def test_batches_limit_is_capped(
    client: TestClient, auth_headers: dict[str, str], fake_vlm: None
) -> None:
    _upload(client, auth_headers, "cap.png")
    body = _batches(client, auth_headers, limit=200)
    assert body["limit"] == 50, "上限就是 50"
