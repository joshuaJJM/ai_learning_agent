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


# ---------------------------------------------------------------------------
# 确定性的假 VLM
# ---------------------------------------------------------------------------
# 放在 conftest 里让所有测试文件共用。它返回一道**答错**的题：
# 正确答案是 C，学生选了 A。这样作业批改、错题、Evidence、标签计分
# 这几条链路都能被确定性地覆盖，完全不依赖网络与模型。

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
    "tags": ["利用导数判断函数单调性与单调区间"],
    "error_type": "transformation",
    "diagnosis": "学生能正确求导，但把导数符号与单调性的对应关系弄反了。",
    "explanation": "f'(x)=3x^2-6x=3x(x-2)，f'(x)>0 得 x<0 或 x>2。",
    "confidence": 0.93,
    "difficulty": 0.5,
}


@pytest.fixture()
def fake_vlm(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import vlm_service
    from app.services.vlm_service import RawQuestion, VlmOutcome

    async def _analyze(images: object, **kwargs: object) -> VlmOutcome:
        outcome = VlmOutcome(generated_by="fake-vlm", model="fake")
        outcome.questions.append(RawQuestion(**DEMO_QUESTION))
        return outcome

    monkeypatch.setattr(vlm_service, "analyze_images", _analyze)
