"""运行时配置。

所有配置都通过环境变量 / backend/.env 注入，代码里不出现任何密钥。
对应 .env.example 的字段说明。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "知迹 Backend"
    debug: bool = False

    # ---- LLM / VLM（OpenAI 兼容端点）----
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    vlm_model: str = "gpt-4o"
    llm_timeout_seconds: float = 60.0
    # 部分自建端点不支持 response_format={"type":"json_object"}，可关掉。
    llm_json_mode: bool = True
    # 置 true 则完全不走网络，全部使用本地 Mock Provider（断网演示保险）。
    force_mock_llm: bool = False

    # ---- 存储 ----
    database_path: str = "data/zhiji.db"

    # ---- 演示可靠性 ----
    # LLM 调用失败时是否自动降级到 Mock（Level 2/3 fallback）。
    llm_fallback_to_mock: bool = True
    # 是否允许命中预置 Demo 缓存（Level 3 fallback）。
    demo_cache_enabled: bool = True

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key) and not self.force_mock_llm


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
