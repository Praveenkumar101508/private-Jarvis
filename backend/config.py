from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "IRA"
    app_env: str = "development"
    app_port: int = 8000
    secret_key: str = "change-me"
    allowed_origins: List[str] = ["http://localhost:3000"]

    # LLM
    llm_provider: str = "openai"
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    openai_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-6"
    groq_model: str = "llama-3.3-70b-versatile"
    ollama_base_url: str = "http://ollama:11434"
    ollama_model: str = "llama3.2"

    # Voice — LiveKit
    livekit_url: str = "ws://livekit:7880"
    livekit_api_key: str = "devkey"
    livekit_api_secret: str = "devsecret"

    # STT
    stt_provider: str = "deepgram"
    deepgram_api_key: str = ""
    whisper_model: str = "base"

    # TTS
    tts_provider: str = "elevenlabs"
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = "21m00Tcm4TlvDq8ikWAM"
    azure_tts_key: str = ""
    azure_tts_region: str = "eastus"
    azure_tts_voice: str = "en-IN-NeerjaNeural"

    # Redis
    redis_url: str = "redis://redis:6379"
    redis_password: str = ""

    # Vector DB
    vector_db: str = "chroma"
    chroma_host: str = "chromadb"
    chroma_port: int = 8001

    # Database
    database_url: str = "postgresql+asyncpg://ira:ira_pass@postgres:5432/ira_db"

    # Search
    tavily_api_key: str = ""
    serp_api_key: str = ""

    # Google
    google_client_id: str = ""
    google_client_secret: str = ""

    # Notifications
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Multilingual
    default_language: str = "en"
    supported_languages: List[str] = ["en", "hi", "te", "ta", "kn", "mr", "bn", "gu", "pa", "ml"]

    # Proactive worker
    proactive_worker_interval: int = 300
    morning_briefing_time: str = "07:30"
    timezone: str = "Asia/Kolkata"

    # Monitoring
    sentry_dsn: str = ""
    log_level: str = "INFO"


settings = Settings()
