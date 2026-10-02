"""临时包装器：把本地 shell 脚本上传到远端执行，再回传输出。

用法：python tools/_rex.py <local_script.sh>
用完即删。
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from tools.remote import build_remote  # noqa: E402

REMOTE_PATH = "/tmp/_dsh_task.sh"


def main() -> int:
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not argv:
        print("usage: python tools/_rex.py <local_script.sh>")
        return 2

    local = Path(argv[0])
    if not local.is_file():
        print(f"script not found: {local}")
        return 2

    body = local.read_text(encoding="utf-8")
    remote = build_remote()
    try:
        with remote._sftp.file(REMOTE_PATH, "w") as handle:
            handle.write(body)
        code, out, err = remote.run(f"bash {REMOTE_PATH}", timeout=300.0)

        # 直接写 UTF-8 字节到 stdout，绕开 Windows 控制台的 GBK 编码限制
        sys.stdout.buffer.write(out.encode("utf-8", "replace"))
        sys.stdout.buffer.flush()
        if err.strip():
            sys.stdout.buffer.write(b"--- STDERR ---\n" + err.encode("utf-8", "replace"))
            sys.stdout.buffer.flush()
        sys.stdout.buffer.write(f"\n[remote exit={code}]\n".encode())
        sys.stdout.buffer.flush()

        remote.run(f"rm -f {REMOTE_PATH}")
        return code
    finally:
        remote.close()


if __name__ == "__main__":
    raise SystemExit(main())
