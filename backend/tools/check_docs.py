"""核对 docs/API.md 是否覆盖了全部真实接口。

手写文档最大的风险是悄悄过期。docs/API.md 是给人和 agent 直接读的
（读它比翻代码省 token），所以它必须与代码保持一致 —— 这个脚本用来验证。

用法：
    cd backend
    .venv/bin/python tools/check_docs.py

退出码 0 = 无缺口；1 = 有接口没写进文档。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_ROOT.parent
DOC_PATH = REPO_ROOT / "docs" / "API.md"

sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app  # noqa: E402

# 文档里可能用简写（/demo/seed 指 /api/v1/demo/seed，{kp_id} 指 {knowledge_point_id}）
_PARAM_ALIASES = re.compile(
    r"\{(knowledge_point_id|wrong_question_id|analysis_id|session_id|book_id|kp_id|wq_id|id)\}"
)


def _normalize(route: str) -> str:
    route = _PARAM_ALIASES.sub("{id}", route)
    if not route.startswith("/api/") and not route.startswith("/health") and route != "/":
        route = "/api/v1" + route
    return route


def main() -> int:
    spec = app.openapi()
    actual = {
        f"{method.upper()} {path}"
        for path, operations in spec["paths"].items()
        for method in operations
    }

    if not DOC_PATH.exists():
        print(f"找不到文档: {DOC_PATH}")
        return 1

    document = DOC_PATH.read_text(encoding="utf-8")
    documented: set[str] = set()
    for match in re.finditer(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/[^\s`,)]*)", document):
        documented.add(f"{match.group(1)} {_normalize(match.group(2).split('?')[0])}")

    actual_normalized: set[str] = set()
    for entry in actual:
        method, _, path = entry.partition(" ")
        actual_normalized.add(f"{method} {_normalize(path)}")
    missing = sorted(actual_normalized - documented)

    print(f"代码接口数 : {len(actual)}")
    print(f"文档提及数 : {len(documented)}")
    if missing:
        print(f"文档未覆盖 : {len(missing)} 个")
        for item in missing:
            print(f"    - {item}")
        return 1
    print("文档未覆盖 : 无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
