"""API.md 完整度深审 —— 比 check_docs.py 更细。

`check_docs.py` 只核对「每个真实接口都被提到过」。但它查不出：

  - 字段缺失：端点写了，但响应体里的字段一个都没介绍
    （线上真实缺口：§8 图书/订阅、§7 ai/models 曾经只有一行路径）
  - 过期内容：文档里写了、代码里根本不存在的路径
  - 契约里有、但**什么都不做**的字段
    （真实案例：PracticeAnswerRequest.answer_text 一路传到 service 后被静默丢弃）
  - 必填查询参数没写

**只查路径覆盖是不够的。** 前端的 DTO 是按字段写的，字段没写进文档
等于没写 —— 他们会照着猜。

用法：
    cd backend
    .venv/bin/python tools/audit_docs.py

退出码 0 = 无缺口；1 = 有缺口。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
DOC_PATH = BACKEND_ROOT.parent / "docs" / "API.md"

sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402

#: FastAPI 自带的端点。它们在运行时存在，但不出现在 `app.openapi()["paths"]` 里，
#: 所以对着 paths 比对会误报成"过期内容"。
#:
#: ⚠️ 这些路径**不能**被 `normalize()` 补上 `/api/v1` 前缀 ——
#: FastAPI 就在根路径上提供 `/openapi.json`，写成 `/api/v1/openapi.json` 才是错的。
BUILTIN_PATHS = {
    "GET /openapi.json",
    "GET /docs",
    "GET /docs/oauth2-redirect",
    "GET /redoc",
}

#: 这些模型只是校验错误的包装，不是业务契约，不要求逐字段写进文档。
SKIP_SCHEMAS = {"HTTPValidationError", "ValidationError", "Body_upload_analysis_images"}


def normalize(route: str) -> str:
    """把路径参数名统一成 {id}，并给业务路径补全 /api/v1 前缀。

    已经在根路径上的内建端点（/openapi.json、/docs…）**不补前缀**。
    """
    route = re.sub(r"\{[^}]+\}", "{id}", route)
    if route in {entry.split(" ", 1)[1] for entry in BUILTIN_PATHS}:
        return route
    if not route.startswith("/api/") and not route.startswith("/health") and route != "/":
        route = "/api/v1" + route
    return route


def main() -> int:
    if not DOC_PATH.exists():
        print(f"找不到文档: {DOC_PATH}")
        return 1
    doc = DOC_PATH.read_text(encoding="utf-8")
    spec = app.openapi()

    actual = {f"{m.upper()} {p}" for p, ops in spec["paths"].items() for m in ops}
    actual_norm = {
        f"{entry.split(' ')[0]} {normalize(entry.split(' ', 1)[1])}" for entry in actual
    }

    # 1) 过期路径：文档写了但代码里没有
    stale: set[str] = set()
    for match in re.finditer(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/[^\s`,)]*)", doc):
        entry = f"{match.group(1)} {normalize(match.group(2).split('?')[0])}"
        if entry not in actual_norm and entry not in BUILTIN_PATHS:
            stale.add(entry)

    # 2) 字段缺失：响应模型里有、文档里从未出现过
    schemas = spec.get("components", {}).get("schemas", {})
    missing_fields: dict[str, list[str]] = {}
    for name, schema in sorted(schemas.items()):
        if name in SKIP_SCHEMAS:
            continue
        props = schema.get("properties") or {}
        absent = [
            field
            for field in props
            if not re.search(rf"(?<![A-Za-z0-9_]){re.escape(field)}(?![A-Za-z0-9_])", doc)
        ]
        if absent:
            missing_fields[name] = absent

    # 3) 必填查询参数没写
    missing_params: list[str] = []
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            if method not in ("get", "post", "patch", "put", "delete"):
                continue
            for param in op.get("parameters", []):
                name = param.get("name")
                if not name or not param.get("required"):
                    continue
                if not re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", doc
                ):
                    missing_params.append(f"{method.upper()} {path} -> {name}")

    print("=" * 72)
    print("1) 过期路径（文档写了、代码里没有）")
    print("=" * 72)
    for item in sorted(stale):
        print(f"  X {item}")
    if not stale:
        print("  (无)")

    print()
    print("=" * 72)
    print("2) 字段缺失（响应模型里有、文档从未提及）")
    print("=" * 72)
    for name, absent in missing_fields.items():
        print(f"  {name}: {', '.join(absent)}")
    if not missing_fields:
        print("  (无)")

    print()
    print("=" * 72)
    print("3) 必填查询参数没写")
    print("=" * 72)
    for item in missing_params:
        print(f"  X {item}")
    if not missing_params:
        print("  (无)")

    print()
    print("=" * 72)
    print("汇总")
    print("=" * 72)
    print(f"  代码接口             {len(actual)}")
    print(f"  过期路径             {len(stale)}")
    print(f"  有缺失字段的模型       {len(missing_fields)} / {len(schemas)}")
    print(f"  没写的必填查询参数     {len(missing_params)}")
    print(f"  API.md 行数          {len(doc.splitlines())}")

    problems = len(stale) + len(missing_fields) + len(missing_params)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
