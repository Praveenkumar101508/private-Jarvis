"""
IRA — Intelligent Responsive Assistant
FastAPI application entry point
"""
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from routers import chat, voice, health, auth
from startup_check import run_startup_checks
from db.connection import close_pool

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("IRA starting", env=settings.app_env)
    if settings.sentry_dsn:
        sentry_sdk.init(dsn=settings.sentry_dsn, traces_sample_rate=0.2)
    await run_startup_checks()
    yield
    await close_pool()
    log.info("IRA shutting down")


app = FastAPI(
    title="IRA — Intelligent Responsive Assistant",
    description=(
        "IRA is a warm, multilingual AI assistant with an Indian female persona. "
        "She understands voice and text, remembers context, and proactively helps you."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/chat", tags=["Chat"])
app.include_router(voice.router, prefix="/voice", tags=["Voice"])
app.include_router(auth.router, prefix="/auth", tags=["Auth"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    log.error("unhandled_error", error=str(exc))
    return JSONResponse(status_code=500, content={"detail": "Something went wrong. IRA is on it!"})
