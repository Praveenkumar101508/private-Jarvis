"""
Central configuration — all values come from environment variables.
Pydantic-settings validates types and provides clear error messages for missing vars.

MODEL TIERS (2026):
  Fast      — Qwen3-8B   (conversational, <2s TTFT)
  Deep      — Qwen3-14B or DeepSeek-R1-Distill-14B (complex reasoning, code)
  Reasoning — DeepSeek-R1-Distill-32B or Qwen3-32B  (Think Mode / DeepSearch)

CLOUD UPGRADE PATH (8×H100 80GB):
  Fast      — Qwen3-30B-A3B  (MoE, fast despite 30B params)
  Deep      — Qwen3-72B      (dense, beats GPT-4o on most benchmarks)
  Reasoning — DeepSeek-R1 671B or Qwen3-235B-A22B (MoE, world-class reasoning)
  Vision    — Qwen3-VL-72B   (multimodal, beats Gemini 1.5 Pro on vision evals)
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
    ira_version: str = "1.0.0"
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
    # Fast path — Qwen3-8B (2026: best small model, beats Llama 3.1 8B significantly)
    # Cloud upgrade: set FAST_MODEL=Qwen/Qwen3-30B-A3B (MoE, fits in 2×H100)
    vllm_fast_url: str = "http://vllm-fast:8001/v1"
    vllm_fast_model: str = "qwen3-fast"
    # Deep path — DeepSeek-R1-Distill-Qwen-14B (reasoning + code, beats Qwen2.5 14B)
    # Cloud upgrade: set DEEP_MODEL=Qwen/Qwen3-72B (requires 4×H100 80GB)
    vllm_deep_url: str = "http://vllm-deep:8002/v1"
    vllm_deep_model: str = "qwen3-deep"
    # Reasoning path — dedicated endpoint for Think Mode + DeepSearch
    # Falls back to deep path if VLLM_REASONING_URL is not set
    # Cloud upgrade: set REASONING_MODEL=deepseek-ai/DeepSeek-R1 or Qwen/Qwen3-235B-A22B
    vllm_reasoning_url: str = ""    # e.g. http://vllm-reasoning:8003/v1
    vllm_reasoning_model: str = "qwen3-reasoning"

    # Routing thresholds
    fast_max_tokens: int = 4096     # Upgraded: Qwen3 handles longer outputs at fast tier
    deep_max_tokens: int = 16384    # Upgraded: 16k for deep reasoning tasks
    reasoning_max_tokens: int = 32768  # Full context for Think Mode chains
    fast_temperature: float = 0.6
    deep_temperature: float = 0.3    # Lower temp for deterministic reasoning
    reasoning_temperature: float = 0.1  # Near-deterministic for step-by-step thinking

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
    # IANA timezone for end-of-day calculations in briefings (e.g. "Asia/Kolkata")
    briefing_timezone: str = "UTC"

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
    # Public WebSocket URL returned to the frontend browser client
    # e.g. wss://jarvis.yourdomain.com  or  ws://localhost:7880
    # Falls back to wss://{ira_domain}/livekit if not set
    livekit_public_url: str = ""

    # ── Webhooks ──────────────────────────────────────────────────────────────
    webhook_secret: str = ""    # Shared secret for validating inbound webhooks

    # ── Owner / Biometric Gate ────────────────────────────────────────────────
    owner_name: str = "Praveen Kumar Kamineti"
    biometric_threshold: float = 0.75   # Cosine similarity floor for voice auth

    # ── Career Tools ──────────────────────────────────────────────────────────
    github_token: str = ""
    apify_api_token: str = ""
    # Fix #47: Apify actor IDs as env vars so they can be updated without a
    # code change if Apify deprecates or renames an actor.
    apify_linkedin_actor: str = "BHzefUZlZRKWxkTck"
    apify_indeed_actor: str = "misceres/indeed-scraper"
    apify_fallback_actor: str = "apify/web-scraper"

    # ── Voice Service ─────────────────────────────────────────────────────────
    # JWT sub that the voice agent uses — only this identity may set is_voice_owner
    ira_voice_service_username: str = "ira-voice"

    # ── X / Twitter Search ───────────────────────────────────────────────────
    # Official X API v2 bearer token — get at developer.x.com (required for best results)
    twitter_bearer_token: str = ""
    # Cheap third-party X API fallback (e.g. twitterapi.io) — $5/month, no rate limits
    x_fallback_api_url: str = "https://api.twitterapi.io"
    x_fallback_api_key: str = ""

    # ── Database Backup ───────────────────────────────────────────────────────
    # Fix L5: moved from module-level os.getenv() in backup.py to lazy config
    backup_dir: str = "/backups"          # Path to the backup volume (BACKUP_DIR)
    backup_keep: int = 7                  # Number of most-recent backups to retain

    # ── Security Monitor Log Paths ────────────────────────────────────────────
    # Fix L16: moved from module-level os.getenv() in security_monitor.py to lazy config
    nginx_log_path: str = "/var/log/nginx/access.log"
    ssh_log_path: str = "/var/log/auth.log"   # /var/log/secure on RHEL/CentOS

    # ── Replicate Audio/Music Models ──────────────────────────────────────────
    # Fix L15: moved from module-level os.getenv() in audio_gen.py to lazy config
    replicate_music_model: str = (
        "meta/musicgen:671ac645ce5e552cc63a54a2bbff63fcf798043055d2dac5fc9e36a837eedcfb"
    )
    replicate_music_stereo_model: str = "meta/musicgen-stereo-melody-large"
    replicate_bark_model: str = (
        "suno-ai/bark:b76242b40d67c76ab6742e987628a2a9ac019e11d56ab96c4e91ce03b79b2787"
    )
    replicate_sfx_model: str = (
        "haoheliu/audio-ldm:b61392adecdd660326fc9cfc5398182437dbe5e97b5decfb36e1a36de68b5b95"
    )

    # ── Image Generation ──────────────────────────────────────────────────────
    # Provider: "replicate" (cloud, Flux Schnell) | "sd_webui" (local SD WebUI) | "comfyui"
    # Cloud upgrade: "replicate" with REPLICATE_API_TOKEN gives instant Flux Pro access
    image_gen_url: str = ""            # SD WebUI / ComfyUI local endpoint
    image_gen_provider: str = "replicate"  # "replicate" | "sd_webui" | "comfyui"
    replicate_api_token: str = ""
    flux_model: str = "black-forest-labs/flux-schnell"  # Replicate model ID for image gen
    # Fix #73: pix2pix model version as config so it survives Replicate model updates
    replicate_pix2pix_model: str = (
        "timbrooks/instruct-pix2pix:"
        "30c1d0b916a6f8efce20493f5d61ee27491ab2a60437c13c588468b9810ec23f"
    )

    # ── Vision Model ──────────────────────────────────────────────────────────
    # Multimodal endpoint for image analysis (Qwen3-VL or LLaVA-NeXT)
    # Defaults to the deep path which should be a vision-capable model
    # Cloud upgrade: set VLLM_VISION_URL=http://vllm-vision:8004/v1 with Qwen3-VL-72B
    vllm_vision_url: str = ""
    vllm_vision_model: str = "qwen3-vl"

    # ── Dev Mode (Shadow PC / local development) ──────────────────────────────
    # DEV_MODE=true routes LLM calls to a local Ollama instance,
    # bypasses biometric gate, and auto-authenticates as admin.
    # NEVER enable in production.
    dev_mode: bool = False
    # Ollama base URL — host.docker.internal reaches Windows host from WSL2/Docker
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    # Ollama model to use for all requests in dev mode
    # Recommended: ollama pull qwen3:8b (best 2026 small model)
    dev_model: str = "qwen3:8b"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
