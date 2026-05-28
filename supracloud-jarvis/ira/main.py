"""
SupraCloud IRA — FastAPI application entry point.

Startup sequence:
  1. Connect to PostgreSQL pool
  2. Connect to Redis
  3. Warm the BGE embedding model (CPU)
  4. Compile the LangGraph agent graph
  5. Register all API routers

Shutdown sequence:
  1. Close DB pool
  2. Close Redis connection
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config import get_settings
from utils.db import init_pool, close_pool
from utils.redis_client import init_redis, close_redis
from memory.embeddings import preload_model
from agents.graph import get_graph, init_checkpointer, close_checkpointer

from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.agents import router as agents_router
from api.routes.tasks import router as tasks_router
from api.routes.notifications import router as notifications_router
from api.routes.briefing import router as briefing_router
from api.routes.voice import router as voice_router
from api.routes.webhooks import router as webhooks_router
from api.routes.backup import router as backup_router
from api.routes.image_gen import router as image_gen_router
from api.routes.architect import router as architect_router
from api.routes.video_gen import router as video_gen_router
from api.routes.document_create import router as document_create_router
from api.routes.design_tools import router as design_tools_router
from api.routes.computer_use import router as computer_use_router
from api.routes.audio_gen import router as audio_gen_router
from api.routes.deep_research import router as deep_research_router
from api.routes.multimodal import router as multimodal_router
from api.middleware.auth import authenticate_user, create_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("jarvis")


# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


async def _validate_config(cfg) -> None:
    """Warn about common misconfiguration issues at startup."""
    warnings = []

    if cfg.owner_name in ("Swetha Devisetty", "", "Change Me"):
        warnings.append("OWNER_NAME is not set to your real name")

    if cfg.ira_admin_password in ("CHANGE_ME_strong_password_here", "admin", "password"):
        warnings.append("IRA_ADMIN_PASSWORD is using the default placeholder — change it!")

    if cfg.ira_secret_key in ("CHANGE_ME_ira_secret_key_here", ""):
        warnings.append("IRA_SECRET_KEY is not set — JWT security is broken!")

    if not getattr(cfg, "telegram_bot_token", None) and not getattr(cfg, "smtp_host", None):
        warnings.append("No notification channel configured (Telegram or SMTP) — alerts will not be delivered")

    for w in warnings:
        logger.warning(f"⚠️  CONFIG WARNING: {w}")

    if any("broken" in w.lower() or "not set" in w.lower() for w in warnings):
        logger.warning("Fix the above config warnings before going to production.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()

    # Initialise OpenTelemetry (no-op if OTLP_ENDPOINT not set)
    from utils.telemetry import setup_telemetry
    setup_telemetry(service_name="ira-api")

    if cfg.dev_mode:
        # Fix P9: refuse to start DEV_MODE against a public domain to prevent
        # accidentally exposing a fully open admin endpoint on the internet.
        if not cfg.is_local_domain:
            raise RuntimeError(
                f"DEV_MODE=true is set but IRA_DOMAIN={cfg.ira_domain!r} is not a "
                "localhost/private address. Refusing to start — this would expose an "
                "unauthenticated admin endpoint on a public domain. "
                "Set DEV_MODE=false or use a local domain."
            )
        logger.warning("=" * 70)
        logger.warning("⚠️  DEV_MODE ENABLED — AUTH AND BIOMETRICS ARE DISABLED  ⚠️")
        logger.warning("   - Authentication bypassed (any token accepted)")
        logger.warning("   - Biometric gate disabled (all requests treated as owner)")
        logger.warning("   - All LLM calls routed to local Ollama")
        logger.warning("   NEVER USE IN PRODUCTION!")
        logger.warning("=" * 70)
    logger.info(f"Jarvis {cfg.ira_version} starting up...")

    # Initialise connections
    await init_pool()
    logger.info("PostgreSQL pool ready")

    # Fix P22: run durable schema migrations on every boot so upgrades work on
    # existing volumes (docker-entrypoint-initdb.d only fires on brand-new volumes).
    from utils.migrations import run_migrations
    from utils.db import get_pool
    await run_migrations(get_pool())

    await init_redis()
    logger.info("Redis connection ready")

    # Warm embedding model in background — don't block startup
    import asyncio
    _t = asyncio.create_task(_warm_embeddings())
    _t.add_done_callback(lambda t: t.exception() and logger.warning(f"Embedding warm-up failed: {t.exception()}"))

    # Initialise LangGraph checkpointer (AsyncPostgresSaver → persistent state)
    await init_checkpointer(cfg.database_dsn)
    logger.info("LangGraph agent graph compiled")

    await _validate_config(cfg)

    logger.info("IRA is online. Good morning.")
    yield

    # Graceful shutdown
    await close_checkpointer()
    await close_pool()
    await close_redis()
    logger.info("IRA shutting down. Goodbye.")


async def _warm_embeddings():
    import asyncio
    await asyncio.sleep(2)  # Let the server finish starting first
    try:
        preload_model()
        logger.info("BGE embedding model warmed and ready")
    except Exception as e:
        logger.warning(f"Embedding model warm-up failed: {e}")


# ── App factory ────────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    cfg = get_settings()

    app = FastAPI(
        title="SupraCloud IRA",
        description="Private sovereign AI assistant — fully self-hosted.",
        version=cfg.ira_version,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — only allow localhost in development; production uses domain only
    allowed_origins = [f"https://{cfg.ira_domain}"]
    if cfg.dev_mode:
        allowed_origins += ["http://localhost:3000", "http://127.0.0.1:3000"]
    # Fix #45: PATCH and PUT were missing — endpoints that use them (architect
    # apply, profile updates) would fail CORS preflight in the browser. OPTIONS
    # is implied by CORSMiddleware but listed explicitly for clarity.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Auth endpoint (not a router — keeps it simple) ────────────────────────
    from fastapi.security import OAuth2PasswordRequestForm
    from fastapi import Depends, Form

    @app.post("/auth/token", tags=["auth"], summary="Get a JWT token")
    @limiter.limit("5/minute")   # Fix P10: app-layer brute-force protection (nginx may be bypassed)
    async def login(
        request: Request,
        form: OAuth2PasswordRequestForm = Depends(),
        totp_code: str | None = Form(None),  # Feat P26: optional TOTP field
    ):
        if not authenticate_user(form.username, form.password):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
            )
        # Feat P26: if TOTP is enrolled, require a valid code on every login
        from utils.db import acquire as _acquire
        async with _acquire() as conn:
            _totp_row = await conn.fetchrow(
                "SELECT secret FROM totp_secrets WHERE username=$1", form.username
            )
        if _totp_row:
            import pyotp as _pyotp
            if not totp_code or not _pyotp.TOTP(_totp_row["secret"]).verify(totp_code, valid_window=1):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "TOTP code required or invalid"},
                )
        return create_token(form.username)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(tasks_router, prefix="/api/v1")
    app.include_router(briefing_router, prefix="/api/v1")
    app.include_router(notifications_router)         # /notifications + /ws/notifications
    app.include_router(voice_router, prefix="/api/v1")   # /voice/token + /voice/enroll
    app.include_router(webhooks_router)              # /webhooks/lead + /webhooks/booking
    app.include_router(backup_router, prefix="/api/v1")      # /backup/list + /backup/download + /backup/restore
    app.include_router(image_gen_router, prefix="/api/v1")       # /image/generate + /image/edit
    app.include_router(architect_router, prefix="/api/v1")       # /architect/propose + /implement + /apply
    app.include_router(video_gen_router, prefix="/api/v1")       # /video/generate + /video/understand
    app.include_router(document_create_router, prefix="/api/v1") # /document/create + /document/download
    app.include_router(design_tools_router, prefix="/api/v1")    # /design/generate + /design/download
    app.include_router(computer_use_router, prefix="/api/v1")    # /computer/use + /computer/screenshot
    app.include_router(audio_gen_router, prefix="/api/v1")       # /audio/generate + /audio/tts + /audio/transcribe
    app.include_router(deep_research_router, prefix="/api/v1")   # /research/deep + /research/article + /research/report
    app.include_router(multimodal_router, prefix="/api/v1")      # /multimodal/analyse

    from api.routes.files import router as files_router
    app.include_router(files_router, prefix="/api/v1")           # Feat P25: /files upload/list/download/delete

    from api.routes.totp import router as totp_router
    app.include_router(totp_router)                              # Feat P26: /auth/totp/enroll + /auth/totp/verify

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled error: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal error occurred. IRA is investigating."},
        )

    return app


app = create_app()

# Auto-instrument FastAPI routes (adds trace spans for every HTTP request)
try:
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    FastAPIInstrumentor.instrument_app(app)
    logger.info("OpenTelemetry FastAPI instrumentation active")
except Exception:
    pass  # telemetry is always optional
