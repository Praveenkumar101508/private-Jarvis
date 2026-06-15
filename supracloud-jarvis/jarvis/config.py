"""
Central configuration — all values come from environment variables.
Pydantic-settings validates types and provides clear error messages for missing vars.
"""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Identity ──────────────────────────────────────────────────────────────
    jarvis_version: str = "0.2.0"
    jarvis_domain: str = "jarvis.local"

    # ── Auth ──────────────────────────────────────────────────────────────────
    jarvis_secret_key: str
    jarvis_admin_username: str = "admin"
    jarvis_admin_password: str
    # JWT tokens expire after 24 hours
    token_expire_hours: int = 24

    # ── Database ──────────────────────────────────────────────────────────────
    postgres_user: str = "jarvis"
    postgres_password: str
    postgres_db: str = "jarvis_db"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_dsn(self) -> str:
        """asyncpg-native DSN (no dialect prefix)."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_password: str
    redis_host: str = "redis"
    redis_port: int = 6379

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    # ── vLLM Endpoints ────────────────────────────────────────────────────────
    vllm_api_key: str
    # Fast path — Llama 3.1 8B AWQ
    vllm_fast_url: str = "http://vllm-fast:8001/v1"
    vllm_fast_model: str = "llama-fast"
    # Deep path — Qwen 2.5 14B AWQ
    vllm_deep_url: str = "http://vllm-deep:8002/v1"
    vllm_deep_model: str = "qwen-deep"

    # Routing thresholds
    fast_max_tokens: int = 2048
    deep_max_tokens: int = 8192
    fast_temperature: float = 0.7
    deep_temperature: float = 0.4    # Lower temp for reasoning tasks

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-large-en-v1.5"
    embedding_dim: int = 1024
    embedding_device: str = "cpu"     # Run embeddings on CPU to save VRAM
    rag_top_k: int = 5                # Top-K memories to retrieve per query

    # ── Agent behaviour ───────────────────────────────────────────────────────
    # Maximum tool calls per agent turn (safety limit)
    max_tool_calls: int = 10
    # Conversation context window injected into prompts (token estimate)
    max_context_messages: int = 20


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
