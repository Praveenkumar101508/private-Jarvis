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
from agents.graph import get_graph

from api.routes.chat import router as chat_router
from api.routes.health import router as health_router
from api.routes.agents import router as agents_router
from api.middleware.auth import authenticate_user, create_token

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("jarvis")


# ── Rate limiter ───────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_settings()
    logger.info(f"Jarvis {cfg.ira_version} starting up...")

    # Initialise connections
    await init_pool()
    logger.info("PostgreSQL pool ready")

    await init_redis()
    logger.info("Redis connection ready")

    # Warm embedding model in background — don't block startup
    import asyncio
    asyncio.create_task(_warm_embeddings())

    # Compile agent graph (fast, just builds the graph object)
    get_graph()
    logger.info("LangGraph agent graph compiled")

    logger.info("IRA is online. Good morning.")
    yield

    # Graceful shutdown
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

    # CORS — restrict to your domain in production
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"https://{cfg.ira_domain}", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # ── Auth endpoint (not a router — keeps it simple) ────────────────────────
    from fastapi.security import OAuth2PasswordRequestForm
    from fastapi import Depends

    @app.post("/auth/token", tags=["auth"], summary="Get a JWT token")
    async def login(form: OAuth2PasswordRequestForm = Depends()):
        if not authenticate_user(form.username, form.password):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid credentials"},
            )
        return create_token(form.username)

    # ── Routers ───────────────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(chat_router, prefix="/api/v1")
    app.include_router(agents_router, prefix="/api/v1")

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
