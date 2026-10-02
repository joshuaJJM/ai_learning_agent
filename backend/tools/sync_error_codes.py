"""从 errors._CODES 生成 docs/API.md 里的错误码表。

文档手写就一定会漂（之前 SESSION_EXPIRED / RATE_LIMITED / BOOK_NOT_OWNED
就是手写出来的死码），所以改成生成。
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(r"C:\Users\Administrator\Documents\ChatGPT\ai_learning_agent")
sys.path.insert(0, str(ROOT / "backend"))

from app.errors import error_code_catalog  # noqa: E402

# 按 HTTP 状态分组，组内按错误码字母序
GROUP_TITLES = {
    400: "请求不合法",
    401: "认证",
    403: "无权限",
    404: "找不到",
    409: "状态冲突",
    422: "语义不合法",
    429: "限流",
    500: "服务端",
    503: "依赖不可用",
    504: "上游超时",
}

catalog = error_code_catalog()
by_status: dict[int, list[dict]] = {}
for entry in catalog:
    by_status.setdefault(entry["http_status"], []).append(entry)

lines = ["| error_code | HTTP | 含义 |", "|---|---|---|"]
for http_status in sorted(by_status):
    for entry in sorted(by_status[http_status], key=lambda e: e["error_code"]):
        lines.append(
            f"| `{entry['error_code']}` | {http_status} | {entry['description']} |"
        )
table = "\n".join(lines)

path = ROOT / "docs" / "API.md"
text = path.read_text(encoding="utf-8")
pattern = re.compile(r"\| error_code \| HTTP \| 含义 \|\n\|---\|\---\|\---\|\n(?:\|[^\n]*\|\n)+")

if not pattern.search(text):
    raise SystemExit("在 docs/API.md 里找不到错误码表")

updated = pattern.sub(table + "\n", text, count=1)
path.write_text(updated, encoding="utf-8")
print(f"已生成 {len(catalog)} 个错误码，覆盖 {path.relative_to(ROOT)}")
