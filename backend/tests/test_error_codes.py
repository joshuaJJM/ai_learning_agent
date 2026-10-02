"""错误码契约：单一来源、无死码、文档同步、前端可拉取。"""

from __future__ import annotations

import pathlib
import re

from fastapi.testclient import TestClient

from app import errors
from app.errors import ErrorCode

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


# ---------------------------------------------------------------------------
# 单一事实来源
# ---------------------------------------------------------------------------

def test_error_code_enum_covers_every_defined_code() -> None:
    """枚举与 _CODES 必须一一对应 —— 它们是同一个来源派生出来的。"""
    from_codes = set(errors._CODES)
    from_enum = {member.value for member in ErrorCode}
    assert from_enum == from_codes


def test_module_constants_match_the_enum() -> None:
    """业务代码 import 的常量和枚举取值必须一致。"""
    for name in errors._CODES:
        assert getattr(errors, name) == name
        assert name in {m.value for m in ErrorCode}


def test_status_map_covers_every_code() -> None:
    assert set(errors._STATUS_FOR) == set(errors._CODES)


def test_no_dead_error_codes_are_defined() -> None:
    """**回归**：不要再往里放「定义了但从不抛出」的码。

    之前 SESSION_EXPIRED / RATE_LIMITED / BOOK_NOT_OWNED 就是这种，
    前端为它们写了永远走不到的分支。
    """
    assert "SESSION_EXPIRED" not in errors._CODES, "token 不过期，这个码不会出现"
    assert "RATE_LIMITED" not in errors._CODES, "没有实现限流，这个码不会出现"
    assert "BOOK_NOT_OWNED" not in errors._CODES, "没有做题库权限校验，这个码不会出现"


def test_error_info_accepts_every_code_without_validation_error() -> None:
    """`ErrorInfo.error_code` 是 enum，任何取值都必须能通过响应校验。

    漏一个就会在运行时变成 500（响应校验失败），所以逐个验一遍。
    """
    from app.schemas import ErrorInfo

    for code in errors._CODES:
        model = ErrorInfo(error_code=code, message="x")
        assert model.error_code.value == code
        assert model.model_dump(mode="json")["error_code"] == code


# ---------------------------------------------------------------------------
# OpenAPI
# ---------------------------------------------------------------------------

def test_openapi_exposes_error_code_as_enum(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    components = schema["components"]["schemas"]
    assert "ErrorCode" in components, "错误码应当渲染成 enum"
    assert set(components["ErrorCode"]["enum"]) == set(errors._CODES)
    # ErrorInfo 必须引用它，而不是裸 string
    assert (
        components["ErrorInfo"]["properties"]["error_code"].get("$ref")
        == "#/components/schemas/ErrorCode"
    )


# ---------------------------------------------------------------------------
# meta 接口
# ---------------------------------------------------------------------------

def test_meta_error_codes_endpoint_lists_everything(client: TestClient) -> None:
    body = client.get("/api/v1/meta/error-codes").json()
    assert body["count"] == len(errors._CODES)
    assert set(body["codes"]) == set(errors._CODES)
    assert {item["error_code"] for item in body["items"]} == set(errors._CODES)
    # 每项都要有 HTTP 状态与含义，前端才能直接生成映射表
    for item in body["items"]:
        assert isinstance(item["http_status"], int)
        assert item["description"]


def test_meta_error_codes_needs_no_auth(client: TestClient) -> None:
    """纯常量接口，不带 Authorization 也要能拿到。"""
    assert client.get("/api/v1/meta/error-codes").status_code == 200


def test_meta_knowledge_points_endpoint(client: TestClient) -> None:
    body = client.get("/api/v1/meta/knowledge-points").json()
    assert body["count"] == 17
    assert len(body["items"]) == 17
    assert all(item["id"] and item["name"] for item in body["items"])


# ---------------------------------------------------------------------------
# 文档同步
# ---------------------------------------------------------------------------

def test_api_md_error_table_matches_the_code() -> None:
    """docs/API.md 的错误码表必须由代码生成，不能手写。

    修复方式：`python tools/sync_error_codes.py`
    """
    text = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")
    match = re.search(
        r"\| error_code \| HTTP \| 含义 \|\n\|---\|\---\|\---\|\n((?:\|[^\n]*\|\n)+)",
        text,
    )
    assert match, "docs/API.md 里找不到错误码表"

    documented: dict[str, int] = {}
    for line in match.group(1).strip().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        documented[cells[0].strip("`")] = int(cells[1])

    assert set(documented) == set(errors._CODES), (
        f"文档与代码不一致。多了 {set(documented) - set(errors._CODES)}，"
        f"少了 {set(errors._CODES) - set(documented)}"
    )
    for code, http_status in documented.items():
        assert http_status == errors._STATUS_FOR[code], f"{code} 的状态码不一致"
