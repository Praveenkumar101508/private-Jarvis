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
    ira_version: str = "0.2.0"
    ira_domain: str = "jarvis.local"

    # ── Auth ──────────────────────────────────────────────────────────────────
    ira_secret_key: str
    ira_admin_username: str = "admin"
    ira_admin_password: str
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
    max_tool_calls: int = 10
    max_context_messages: int = 20

    # ── Proactive Intelligence (Phase 4) ──────────────────────────────────────
    # Hour (UTC) to send the morning briefing (default 08:00)
    briefing_hour_utc: int = 8

    # ── Notifications: Telegram ───────────────────────────────────────────────
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── Notifications: Email (SMTP) ───────────────────────────────────────────
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_to: str = ""          # Recipient — defaults to smtp_user if blank

    # ── Calendar: Cal.com ─────────────────────────────────────────────────────
    calcom_api_key: str = ""
    calcom_api_url: str = "https://api.cal.com"

    # ── Calendar: Google ──────────────────────────────────────────────────────
    google_calendar_id: str = ""
    google_service_account_json: str = ""  # Path to service account JSON file

    # ── LiveKit (for voice token generation) ──────────────────────────────────
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_room_name: str = "ira-voice"

    # ── Webhooks ──────────────────────────────────────────────────────────────
    webhook_secret: str = ""    # Shared secret for validating inbound webhooks

    # ── Owner / Biometric Gate ────────────────────────────────────────────────
    owner_name: str = "Swetha Devisetty"
    biometric_threshold: float = 0.75   # Cosine similarity floor for voice auth

    # ── Career Tools ──────────────────────────────────────────────────────────
    github_token: str = ""
    apify_api_token: str = ""

    # ── Dev Mode (Shadow PC / local development) ──────────────────────────────
    # DEV_MODE=true routes LLM calls to a local Ollama instance,
    # bypasses biometric gate, and auto-authenticates as admin.
    # NEVER enable in production.
    dev_mode: bool = False
    # Ollama base URL — host.docker.internal reaches Windows host from WSL2/Docker
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    # Ollama model to use for all requests in dev mode
    dev_model: str = "llama3.2"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
