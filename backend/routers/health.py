from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()


@router.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "IRA — Intelligent Responsive Assistant",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/")
async def root():
    return {
        "name": "IRA",
        "full_name": "Intelligent Responsive Assistant",
        "persona": "Warm Indian female AI assistant",
        "version": "1.0.0",
        "docs": "/docs",
    }
