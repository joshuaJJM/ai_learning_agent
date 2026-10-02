"""远程服务器操作工具（paramiko）。

为什么用 paramiko 而不是系统 ssh：
Windows 自带的 OpenSSH 不支持把密码通过管道喂进去做非交互登录，
首次连接还会卡在 host key 确认上。paramiko 能在脚本里干净地完成
密码认证 + SFTP 传输。

用法：
    python tools/remote.py ping
    python tools/remote.py exec "systemctl status nginx"
    python tools/remote.py deploy
"""

from __future__ import annotations

import argparse
import posixpath
import sys
from pathlib import Path
from typing import Iterable

import paramiko

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings  # noqa: E402

# 这些目录/文件不上传：本地虚拟环境、缓存、运行时数据、本地密钥
EXCLUDE_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".pytest_tmp",
    ".mypy_cache",
    ".ruff_cache",
    "data",
    ".env",
    ".git",
}
EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".db", ".db-wal", ".db-shm"}


class Remote:
    def __init__(self, host: str, port: int, user: str, password: str) -> None:
        self.host = host
        self.port = port
        self.user = user
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            hostname=host,
            port=port,
            username=user,
            password=password,
            timeout=20,
            banner_timeout=30,
            auth_timeout=30,
            look_for_keys=False,
            allow_agent=False,
        )
        self._sftp = self._client.open_sftp()

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._client.close()

    def __enter__(self) -> "Remote":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- 执行 ---------------------------------------------------------------
    def run(self, command: str, timeout: float = 180.0) -> tuple[int, str, str]:
        _, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    def sudo_run(self, command: str, timeout: float = 300.0) -> tuple[int, str, str]:
        """用 sudo -S 从 stdin 喂密码，避免交互卡住。"""
        wrapped = f"sudo -S -p '' bash -lc {_q(command)}"
        _, stdout, stderr = self._client.exec_command(wrapped, timeout=timeout)
        stdout.channel.sendall(self._password + "\n")
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return code, out, err

    # -- 传输 ---------------------------------------------------------------
    def mkdirs(self, remote_dir: str) -> None:
        parts = remote_dir.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}"
            try:
                self._sftp.stat(current)
            except FileNotFoundError:
                self._sftp.mkdir(current)

    def put_file(self, local: Path, remote_path: str) -> None:
        self.mkdirs(posixpath.dirname(remote_path))
        self._sftp.put(str(local), remote_path)

    def upload_tree(
        self, local_root: Path, remote_root: str, extra_excludes: Iterable[str] = ()
    ) -> tuple[int, int]:
        excludes = EXCLUDE_NAMES | set(extra_excludes)
        files = 0
        total = 0
        self.mkdirs(remote_root)
        for path in sorted(local_root.rglob("*")):
            relative = path.relative_to(local_root)
            if any(part in excludes for part in relative.parts):
                continue
            if path.is_dir():
                self.mkdirs(posixpath.join(remote_root, relative.as_posix()))
                continue
            if path.suffix in EXCLUDE_SUFFIXES:
                continue
            target = posixpath.join(remote_root, relative.as_posix())
            self.put_file(path, target)
            files += 1
            total += path.stat().st_size
        return files, total


RUN_SH = """#!/bin/bash
# 由 tools/remote.py 生成。远端用户不在 sudoers 里，所以用 nohup 托管而不是 systemd。
cd "$(dirname "$0")"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port __PORT__ --workers 1
"""

START_SH = """#!/bin/bash
cd "$(dirname "$0")"
if [ -f haoxue.pid ] && kill -0 "$(cat haoxue.pid)" 2>/dev/null; then
  echo "ALREADY_RUNNING pid=$(cat haoxue.pid)"; exit 0
fi
setsid nohup ./run.sh >> service.log 2>&1 < /dev/null &
echo $! > haoxue.pid
sleep 4
if kill -0 "$(cat haoxue.pid)" 2>/dev/null; then
  echo "STARTED pid=$(cat haoxue.pid)"
else
  echo "FAILED_TO_START"; tail -n 30 service.log; exit 1
fi
"""

STOP_SH = """#!/bin/bash
cd "$(dirname "$0")"
if [ -f haoxue.pid ]; then
  kill "$(cat haoxue.pid)" 2>/dev/null && echo "STOPPED pid=$(cat haoxue.pid)"
  sleep 1
  kill -9 "$(cat haoxue.pid)" 2>/dev/null
  rm -f haoxue.pid
else
  echo "NO_PIDFILE"
fi
pkill -f "uvicorn app.main:app" 2>/dev/null
exit 0
"""

PIP_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"


def _q(text: str) -> str:
    return "'" + text.replace("'", "'\"'\"'") + "'"


def build_remote() -> Remote:
    settings = get_settings()
    if not settings.remote_password:
        raise SystemExit("REMOTE_PASSWORD 未配置（请写入 backend/.env）")
    return Remote(
        settings.remote_host, settings.remote_port, settings.remote_user, settings.remote_password
    )


def _service(remote: Remote, action: str) -> str:
    """服务管理。远端用户不在 sudoers 里，所以走 nohup + pidfile。"""
    app_dir = get_settings().remote_app_dir

    if action == "logs":
        _, out, err = remote.run(f"tail -n 80 {app_dir}/service.log 2>/dev/null")
        return out or err

    if action == "status":
        _, out, _ = remote.run(
            f"cd {app_dir} && "
            "(test -f haoxue.pid && kill -0 $(cat haoxue.pid) 2>/dev/null "
            "&& echo \"RUNNING pid=$(cat haoxue.pid)\" || echo NOT_RUNNING); "
            "echo '--- listening ---'; "
            "(ss -ltn 2>/dev/null | grep 17283 || echo 'nothing on 17283'); "
            "echo '--- log tail ---'; tail -n 15 service.log 2>/dev/null"
        )
        return out

    if action == "restart":
        remote.run(f"cd {app_dir} && ./stop.sh")

    script = {"start": "start.sh", "stop": "stop.sh", "restart": "start.sh"}[action]
    _, out, err = remote.run(f"cd {app_dir} && ./{script}")
    return "\n".join(part for part in (out.strip(), err.strip()) if part)


def main() -> int:
    parser = argparse.ArgumentParser(description="远程服务器操作")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ping", help="连接并打印远端环境信息")
    p_exec = sub.add_parser("exec", help="在远端执行命令")
    p_exec.add_argument("command")
    p_deploy = sub.add_parser("deploy", help="上传 backend/ 到远端")
    p_deploy.add_argument("--dir", default=None, help="远端目标目录")
    p_deploy.add_argument(
        "--with-env", action="store_true", help="同时上传本地 .env（含密钥）"
    )
    p_deploy.add_argument(
        "--restart", action="store_true", help="上传后重启 systemd 服务"
    )

    p_boot = sub.add_parser("bootstrap", help="远端首次初始化：建 venv、装依赖、装 systemd")
    p_boot.add_argument("--dir", default=None)
    p_boot.add_argument("--port", type=int, default=None)
    p_boot.add_argument("--force-reinstall", action="store_true")

    p_svc = sub.add_parser("service", help="服务管理（无 sudo，nohup + pidfile）")
    p_svc.add_argument(
        "action",
        choices=["start", "stop", "restart", "status", "logs"],
    )

    args = parser.parse_args()

    remote = build_remote()
    # sudo_run 需要密码
    remote._password = get_settings().remote_password

    try:
        if args.cmd == "ping":
            code, out, err = remote.run(
                "echo '--- whoami ---'; whoami; echo '--- uname ---'; uname -a; "
                "echo '--- python ---'; (python3 --version || echo 'no python3'); "
                "echo '--- pip ---'; (python3 -m pip --version || echo 'no pip'); "
                "echo '--- venv ---'; (python3 -m venv --help >/dev/null 2>&1 && echo 'venv OK' || echo 'venv MISSING'); "
                "echo '--- sudo ---'; (sudo -n true 2>/dev/null && echo 'passwordless sudo' || echo 'sudo needs password'); "
                "echo '--- home ---'; pwd; echo '--- disk ---'; df -h / | tail -1; "
                "echo '--- port 17283 ---'; (ss -ltnp 2>/dev/null | grep 17283 || echo 'nothing on 17283')"
            )
            print(out)
            if err.strip():
                print("STDERR:", err, file=sys.stderr)
            return code

        if args.cmd == "exec":
            code, out, err = remote.run(args.command)
            print(out, end="")
            if err.strip():
                print("STDERR:", err, file=sys.stderr)
            return code

        if args.cmd == "deploy":
            target = args.dir or get_settings().remote_app_dir
            files, total = remote.upload_tree(BACKEND_ROOT, target)
            print(f"上传完成: {files} 个文件, {total / 1024:.1f} KB -> {target}")

            if args.with_env:
                local_env = BACKEND_ROOT / ".env"
                if not local_env.exists():
                    print("!! 本地没有 .env，跳过", file=sys.stderr)
                else:
                    remote.put_file(local_env, posixpath.join(target, ".env"))
                    print("已上传 .env（含密钥）")

            if args.restart:
                print(_service(remote, "restart"))
            return 0

        if args.cmd == "bootstrap":
            settings = get_settings()
            target = args.dir or settings.remote_app_dir
            port = args.port or settings.app_port

            def step(title: str, command: str) -> None:
                print(f"\n--- {title} ---")
                code, out, err = remote.run(command)
                if out.strip():
                    print(out.strip()[-1500:])
                if err.strip():
                    print("stderr:", err.strip()[-800:])
                print(f"exit={code}")

            step("创建目录", f"mkdir -p {target}/data")
            step(
                "创建虚拟环境",
                f"cd {target} && (test -x .venv/bin/python || python3 -m venv .venv) "
                f"&& .venv/bin/python --version",
            )
            reinstall = " --force-reinstall" if args.force_reinstall else ""
            step(
                "安装依赖",
                f"cd {target} && .venv/bin/python -m pip install -q "
                f"-i {PIP_INDEX} --upgrade pip{reinstall} && "
                f".venv/bin/python -m pip install -q -i {PIP_INDEX}{reinstall} "
                f"-r requirements.txt && echo INSTALL_OK",
            )

            # 写启动脚本（远端用户没有 sudo，用 nohup 而不是 systemd）
            for name, template in (
                ("run.sh", RUN_SH.replace("__PORT__", str(port))),
                ("start.sh", START_SH),
                ("stop.sh", STOP_SH),
            ):
                with remote._sftp.file(posixpath.join(target, name), "w") as handle:
                    handle.write(template)
            step("脚本加执行权限", f"chmod +x {target}/*.sh && ls -l {target}/*.sh")

            local_env = BACKEND_ROOT / ".env"
            if local_env.exists():
                remote.put_file(local_env, posixpath.join(target, ".env"))
                print("\n已上传 .env")
            else:
                print("\n!! 本地没有 .env，远端将使用 Mock 模式", file=sys.stderr)

            print("\n--- 启动服务 ---")
            print(_service(remote, "start"))
            return 0

        if args.cmd == "service":
            print(_service(remote, args.action))
            return 0
    finally:
        remote.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
