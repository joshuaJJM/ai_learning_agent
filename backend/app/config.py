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

    app_name: str = "好学 Backend"
    debug: bool = False

    # ---- LLM / VLM（OpenAI 兼容端点）----
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "deepseek-ai/DeepSeek-V3.2"
    vlm_model: str = "Qwen/Qwen3-VL-32B-Instruct"
    # 主力模型不可用时的备选（实测 8B 版本识别这道题同样正确且更省）
    vlm_fallback_model: str = "Qwen/Qwen3-VL-8B-Instruct"
    llm_fallback_model: str = "Qwen/Qwen2.5-72B-Instruct"
    llm_timeout_seconds: float = 60.0
    # 部分自建端点不支持 response_format={"type":"json_object"}，可关掉。
    llm_json_mode: bool = True
    # 置 true 则完全不走网络，全部使用本地 Mock Provider（断网演示保险）。
    force_mock_llm: bool = False

    # ---- 存储 ----
    # 生产用 MySQL（远端 127.0.0.1，仅服务器内可连）；本地开发与测试回落到 SQLite。
    # 只要 MYSQL_HOST 配了就走 MySQL。
    mysql_host: str = ""
    mysql_port: int = 3306
    mysql_user: str = ""
    mysql_password: str = ""
    mysql_database: str = "hackathon"
    # 没配 MySQL 时用这个 SQLite 文件
    database_path: str = "data/haoxue.db"

    # ---- 服务监听 ----
    app_host: str = "0.0.0.0"
    app_port: int = 17283
    # 对外可访问的基址，用于拼图片 URL 下发给客户端
    public_base_url: str = "http://121.43.137.176:17283"

    # ---- 远程部署（tools/remote.py 用）----
    remote_host: str = "121.43.137.176"
    remote_port: int = 22
    remote_user: str = "hackathon"
    remote_password: str = ""
    remote_app_dir: str = "/home/hackathon/haoxue-backend"

    # ---- 演示可靠性 ----
    # LLM 调用失败时是否自动降级到 Mock（Level 2/3 fallback）。
    llm_fallback_to_mock: bool = True
    # 是否允许命中预置 Demo 缓存（Level 3 fallback）。
    demo_cache_enabled: bool = True

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_key) and not self.force_mock_llm

    @property
    def use_mysql(self) -> bool:
        """配了 host + user 就用 MySQL，否则用 SQLite（本地开发/测试）。"""
        return bool(self.mysql_host and self.mysql_user)

    @property
    def storage_backend(self) -> str:
        return "mysql" if self.use_mysql else "sqlite"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
