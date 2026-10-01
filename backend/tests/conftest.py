"""测试夹具。

关键点：**在导入 app 之前**改掉环境变量，否则 pydantic-settings
会先读走 .env 里的真实配置（含真实数据库路径）。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 注意：不要用 tempfile.gettempdir()。在受限沙箱里系统临时目录不可写，
# Python 会静默回退到 CWD，把测试数据库散进仓库。这里锚到工作区内
# 一个已被 .gitignore 忽略的固定目录。
_TMP = BACKEND_DIR / ".pytest_tmp"
if _TMP.exists():
    shutil.rmtree(_TMP, ignore_errors=True)
_TMP.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_PATH"] = str(_TMP / "test.db")
os.environ["FORCE_MOCK_LLM"] = "true"
os.environ["DEMO_CACHE_ENABLED"] = "false"
os.environ["PUBLIC_BASE_URL"] = "http://testserver"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

FIXTURE_IMAGE = Path(__file__).resolve().parent / "fixtures" / "demo_question_17.png"


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """测试结束清掉临时数据库。"""
    shutil.rmtree(_TMP, ignore_errors=True)


@pytest.fixture(scope="session")
def client() -> TestClient:
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def demo_user(client: TestClient) -> dict:
    response = client.get("/api/v1/auth/demo-user")
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture()
def auth_headers(demo_user: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {demo_user['access_token']}"}
