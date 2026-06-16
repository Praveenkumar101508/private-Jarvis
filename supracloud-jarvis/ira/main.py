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
from fastapi.security import OAuth2PasswordRequestForm  # module scope: FastAPI must resolve it
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
from api.routes.strategy import router as strategy_router
from api.middleware.auth import (
    authenticate_user, create_login_tokens, create_token,
    decode_token, revoke_token, bump_token_version,
)
from utils.canary import canary_router, check_canary_username

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

    if cfg.owner_name in ("CHANGE_ME_your_name", "", "Change Me", "Your Name Here"):
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

    # Sovereignty guard: if the Cortex engine is ON, its gateway MUST be local or
    # prompts could leave the box via a remote gateway. Warn loudly; never block.
    from config import cortex_local_only_warning, research_backends_warning
    _cortex_leak = cortex_local_only_warning()
    if _cortex_leak:
        logger.warning("=" * 70)
        logger.warning("⚠️  CORTEX SOVEREIGNTY WARNING  ⚠️")
        logger.warning(f"   {_cortex_leak}")
        logger.warning("   Point IRA_CORTEX_URL at 127.0.0.1/localhost unless you")
        logger.warning("   truly intend to route through a remote (cloud) gateway.")
        logger.warning("=" * 70)

    # Same for the web-research backends (SearXNG / Crawl4AI) — keep them local.
    _research_leak = research_backends_warning()
    if _research_leak:
        logger.warning("=" * 70)
        logger.warning("⚠️  WEB-RESEARCH SOVEREIGNTY WARNING  ⚠️")
        logger.warning(f"   {_research_leak}")
        logger.warning("   Point SEARXNG_URL / CRAWL4AI_URL at local/self-hosted endpoints.")
        logger.warning("=" * 70)


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

    # Pre-warm the on-device Supertonic TTS so the first POST /voice/say is not cold.
    _ts = asyncio.create_task(_warm_supertonic())
    _ts.add_done_callback(lambda t: t.exception() and logger.warning(f"Supertonic warm-up failed: {t.exception()}"))

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

    # A2: warm the reranker cross-encoder too (only if enabled) so the first
    # memory query isn't slowed by the one-time model load.
    cfg = get_settings()
    if cfg.reranker_enabled:
        try:
            from memory.reranker import preload_model as preload_reranker
            preload_reranker()
            logger.info("BGE reranker model warmed and ready")
        except Exception as e:
            logger.warning(f"Reranker model warm-up failed: {e}")


async def _warm_supertonic():
    """Load the on-device Supertonic TTS engine once at startup (fail-soft).

    Runs the blocking model load off the event loop. If Supertonic isn't installed
    (e.g. a text-only deployment), this is a no-op and POST /voice/say returns 503
    until the engine is available — it never blocks or fails startup.
    """
    import asyncio
    await asyncio.sleep(2)  # let the server finish starting first
    try:
        from voice.tts_supertonic import prewarm
        ready = await asyncio.to_thread(prewarm)
        if ready:
            logger.info("Supertonic TTS engine warmed and ready")
        else:
            logger.info("Supertonic TTS not available — /voice/say will 503 until installed")
    except Exception as e:
        logger.info(f"Supertonic warm-up skipped: {e}")


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
    # Phone access over Tailscale Serve (HTTPS) — allow the *.ts.net origin so the
    # mobile PWA's mic (getUserMedia needs a secure context) and API calls work.
    if getattr(cfg, "ira_ts_host", ""):
        allowed_origins.append(f"https://{cfg.ira_ts_host}")
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

    # P6.2: IP blocklist middleware — runs before all routes; blocked IPs get 403
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response as _Response

    class _IPBlockMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.client:
                from utils.playbooks import is_ip_blocked
                if await is_ip_blocked(request.client.host):
                    return _Response(
                        content='{"detail":"Access denied"}',
                        status_code=403,
                        media_type="application/json",
                    )
            return await call_next(request)

    app.add_middleware(_IPBlockMiddleware)

    # ── Auth endpoint (not a router — keeps it simple) ────────────────────────
    # OAuth2PasswordRequestForm is imported at MODULE scope (top of file). Under
    # `from __future__ import annotations` FastAPI resolves the `form:` annotation as a
    # ForwardRef against module globals; a local import leaves it unresolved -> the
    # /auth/token route raises TypeError("ForwardRef(...) is not callable") at startup.
    from fastapi import Depends, Form

    @app.post("/auth/token", tags=["auth"], summary="Get JWT access + refresh tokens")
    @limiter.limit("5/minute")   # app-layer brute-force protection (nginx may be bypassed)
    async def login(
        request: Request,
        form: OAuth2PasswordRequestForm = Depends(OAuth2PasswordRequestForm),
        totp_code: str | None = Form(None),  # optional TOTP field
    ):
        from utils.account_lockout import is_locked, record_failure, clear_failures

        # P5.2: ghost-username tripwire — fires CRITICAL event, still returns 401
        source_ip = request.client.host if request.client else None
        if await check_canary_username(form.username, source_ip=source_ip):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
            )

        # P2.3: check lockout BEFORE running bcrypt (avoid unnecessary CPU)
        if await is_locked(form.username):
            return JSONResponse(
                status_code=429,
                content={"detail": "Account temporarily locked due to too many failed attempts. Try again later."},
            )

        if not authenticate_user(form.username, form.password):
            _count, _locked = await record_failure(form.username)
            if _locked:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Account locked after too many failed attempts. Try again in 15 minutes."},
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
            )

        # Only enforce TOTP once it has been enrolled and enabled
        from utils.db import acquire as _acquire
        async with _acquire() as conn:
            _totp_row = await conn.fetchrow(
                "SELECT secret FROM totp_secrets WHERE username=$1 AND enabled=TRUE", form.username
            )
        if _totp_row:
            import pyotp as _pyotp
            if not totp_code or not _pyotp.TOTP(_totp_row["secret"]).verify(totp_code, valid_window=1):
                await record_failure(form.username)
                return JSONResponse(
                    status_code=401,
                    content={"detail": "TOTP code required or invalid"},
                )

        # Successful login — clear the failure counter
        await clear_failures(form.username)
        return await create_login_tokens(form.username)

    from fastapi.security import HTTPBearer as _HTTPBearer, HTTPAuthorizationCredentials as _Creds

    _bearer_dep = _HTTPBearer(auto_error=False)

    @app.post("/auth/logout", tags=["auth"], summary="Revoke the current access token")
    async def logout(
        request: Request,
        creds: _Creds | None = Depends(_bearer_dep),
    ):
        """Add the token's jti to the Redis revocation list so it can't be reused."""
        from datetime import datetime, timezone
        if creds is None:
            return JSONResponse(status_code=401, content={"detail": "No token provided"})
        try:
            payload = decode_token(creds.credentials)
            if payload.jti:
                remaining = int((payload.exp - datetime.now(timezone.utc)).total_seconds())
                await revoke_token(payload.jti, max(1, remaining))
        except Exception:
            pass  # always return success to avoid leaking token validity
        return {"message": "Logged out"}

    @app.post("/auth/logout/all", tags=["auth"], summary="Revoke ALL tokens for the current user")
    async def logout_all(
        request: Request,
        creds: _Creds | None = Depends(_bearer_dep),
    ):
        """Bump the per-user token version, invalidating every existing access token."""
        if creds is None:
            return JSONResponse(status_code=401, content={"detail": "No token provided"})
        payload = decode_token(creds.credentials)
        await bump_token_version(payload.sub)
        return {"message": f"All tokens for {payload.sub!r} have been invalidated"}

    @app.post("/auth/refresh", tags=["auth"], summary="Exchange a refresh token for a new access token")
    @limiter.limit("20/minute")
    async def refresh_token_endpoint(
        request: Request,
        creds: _Creds | None = Depends(_bearer_dep),
    ):
        """Verify the refresh token and issue a fresh short-lived access token."""
        from datetime import datetime, timezone
        from api.middleware.auth import _is_revoked, _get_token_version, _make_access_token
        if creds is None:
            return JSONResponse(status_code=401, content={"detail": "No token provided"})
        payload = decode_token(creds.credentials)
        if payload.tok != "refresh":
            return JSONResponse(status_code=400, content={"detail": "Not a refresh token"})
        if payload.jti and await _is_revoked(payload.jti):
            return JSONResponse(status_code=401, content={"detail": "Refresh token revoked"})
        ver = await _get_token_version(payload.sub)
        access_token, _, access_exp = _make_access_token(payload.sub, ver=ver)
        now = datetime.now(timezone.utc)
        from api.middleware.auth import TokenResponse as _TR
        return _TR(
            access_token=access_token,
            expires_in=max(0, int((access_exp - now).total_seconds())),
        )

    # ── Routers ───────────────────────────────────────────────────────────────
    # P5.2: honeypot paths FIRST — must be registered before any catch-all 404
    app.include_router(canary_router)
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
    app.include_router(strategy_router, prefix="/api/v1")        # Phase 6: /strategy/outcome + /strategy/predictions

    from api.routes.files import router as files_router
    app.include_router(files_router, prefix="/api/v1")           # Feat P25: /files upload/list/download/delete

    from api.routes.totp import router as totp_router
    app.include_router(totp_router)                              # Feat P26: /auth/totp/enroll + /auth/totp/verify

    from api.routes.calendar import router as calendar_router
    app.include_router(calendar_router, prefix="/api/v1")        # Feat P27: /calendar/event create + cancel

    from api.routes.profile import router as profile_router
    app.include_router(profile_router, prefix="/api/v1")         # v1 1.4: /profile owner profile (GET/PUT)

    from api.routes.actions import router as actions_router
    app.include_router(actions_router, prefix="/api/v1")         # v1 2.3: /actions (email-with-approval, status)

    from api.routes.research import router as research_router
    app.include_router(research_router, prefix="/api/v1")        # v1 3B.2: /research (web search/read) + doctor

    from api.routes.notes import router as notes_router
    app.include_router(notes_router, prefix="/api/v1")           # Phase 3: /notes (local-first markdown, delete gated)

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
