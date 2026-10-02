"""备用 provider（另一个厂商）的路由与使用。

主厂商整体挂掉时（实测遇到过 SiliconFlow 返 500），同一家的备选模型会一起哑，
只有换厂商才救得回来。所以备用 provider 走自己的 base_url 和 key，
并在两处生效：VLM 兜底链的最后一环，以及二次求解校验。
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services import vlm_service
from app.services.llm import LlmClient, LlmUnavailable

PRIMARY = "Qwen/Qwen3-VL-32B-Instruct"
FALLBACK = "Qwen/Qwen3-VL-8B-Instruct"
BACKUP = "deepseek-flash"


def _settings(**overrides) -> Settings:
    base = {
        "llm_base_url": "https://primary.example/v1",
        "llm_api_key": "primary-key",
        "llm_model": "deepseek-ai/DeepSeek-V3.2",
        "vlm_model": PRIMARY,
        "vlm_fallback_model": FALLBACK,
        "backup_llm_base_url": "https://api.deepseek.com/v1",
        "backup_llm_api_key": "backup-key",
        "backup_llm_model": BACKUP,
        "force_mock_llm": False,
    }
    base.update(overrides)
    return Settings(**base)


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------

def test_backup_model_routes_to_the_backup_provider() -> None:
    client = LlmClient(_settings())
    provider = client.provider_for(BACKUP)

    assert provider.name == "deepseek"
    assert provider.base_url == "https://api.deepseek.com/v1"
    assert provider.api_key == "backup-key"


def test_other_models_route_to_the_primary_provider() -> None:
    client = LlmClient(_settings())
    for model in (PRIMARY, FALLBACK, "deepseek-ai/DeepSeek-V3.2", "随便什么模型"):
        provider = client.provider_for(model)
        assert provider.name == "siliconflow", f"{model} 不该被发到备用厂商"
        assert provider.api_key == "primary-key"


def test_without_a_backup_key_everything_goes_primary() -> None:
    client = LlmClient(_settings(backup_llm_api_key=""))
    assert client.backup_configured is False
    assert client.provider_for(BACKUP).name == "siliconflow"


def test_configured_is_true_with_only_the_backup_key() -> None:
    """主 key 空着、只有备用 key 时，客户端仍应可用。"""
    client = LlmClient(_settings(llm_api_key="", backup_llm_api_key="backup-key"))
    assert client.configured is True
    assert client.backup_configured is True


def test_force_mock_disables_both() -> None:
    client = LlmClient(_settings(force_mock_llm=True))
    assert client.configured is False
    assert client.backup_configured is False


@pytest.mark.asyncio
async def test_calling_a_provider_without_a_key_fails_clearly() -> None:
    """**选中的那个** provider 没 key 时要报清楚，而不是发出一个带着空
    Authorization 的请求（那只会换来一个语义模糊的 401）。

    注意构造：这里让主 key 为空、备用 key 有值，然后用主模型调用 ——
    于是路由到主 provider，它没有 key，应当在**联网之前**就报错。
    """
    client = LlmClient(_settings(llm_api_key="", backup_llm_api_key="backup-key"))
    with pytest.raises(LlmUnavailable) as excinfo:
        await client.complete([{"role": "user", "content": "x"}], model=PRIMARY)
    assert "没有配置 API key" in str(excinfo.value)


def test_headers_use_the_providers_own_key() -> None:
    client = LlmClient(_settings())
    backup_headers = client.headers_for(client.provider_for(BACKUP))
    primary_headers = client.headers_for(client.provider_for(PRIMARY))

    assert backup_headers["Authorization"] == "Bearer backup-key"
    assert primary_headers["Authorization"] == "Bearer primary-key"


# ---------------------------------------------------------------------------
# 二次求解校验用哪个模型
# ---------------------------------------------------------------------------

def test_verification_uses_the_backup_model_when_configured() -> None:
    settings = _settings()
    assert vlm_service.verification_model(settings, LlmClient(settings)) == BACKUP


def test_verification_falls_back_to_the_primary_model() -> None:
    settings = _settings(backup_llm_api_key="")
    assert (
        vlm_service.verification_model(settings, LlmClient(settings))
        == settings.llm_model
    )


def test_verification_can_be_pinned_to_the_primary_model() -> None:
    settings = _settings(verify_with_backup_model=False)
    assert (
        vlm_service.verification_model(settings, LlmClient(settings))
        == settings.llm_model
    )


# ---------------------------------------------------------------------------
# VLM 识别链（直接调生产代码，不抄一份）
# ---------------------------------------------------------------------------

def _chain(settings: Settings) -> list[str]:
    return vlm_service.recognition_models(settings, LlmClient(settings))


def test_vlm_chain_puts_deepseek_before_the_weaker_fallback() -> None:
    """★ 质量优先：DeepSeek 识别质量最高（只是慢），必须排在 8B 之前。"""
    assert _chain(_settings()) == [PRIMARY, BACKUP, FALLBACK]


def test_vlm_chain_starts_with_the_primary_model() -> None:
    assert _chain(_settings())[0] == PRIMARY


def test_vlm_chain_has_no_backup_when_unconfigured() -> None:
    assert _chain(_settings(backup_llm_api_key="")) == [PRIMARY, FALLBACK]


def test_backup_model_is_not_duplicated_in_the_chain() -> None:
    """万一有人把备用模型配成了和主模型同一个名字。"""
    assert _chain(_settings(backup_llm_model=PRIMARY, vlm_fallback_model=PRIMARY)) == [
        PRIMARY
    ]


def test_fallback_is_dropped_when_it_equals_the_primary() -> None:
    assert _chain(_settings(vlm_fallback_model=PRIMARY)) == [PRIMARY, BACKUP]


def test_health_reports_the_backup_provider(client) -> None:
    body = client.get("/health").json()
    assert "backup_llm_model" in body
    assert "backup_llm_configured" in body
