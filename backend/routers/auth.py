"""
Auth router — Google OAuth for calendar integration.

Flow:
  GET /auth/google           — redirect user to Google consent screen
  GET /auth/google/callback  — exchange code for tokens; upsert into users.google_tokens
"""
import json

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google_auth_oauthlib.flow import Flow

from config import settings

log = structlog.get_logger()
router = APIRouter()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

_CLIENT_CONFIG = {
    "web": {
        "client_id": "",          # filled at request time from settings
        "client_secret": "",
        "redirect_uris": [],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}


def _build_flow() -> Flow:
    config = {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uris": [settings.google_redirect_uri],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = Flow.from_client_config(config, scopes=SCOPES)
    flow.redirect_uri = settings.google_redirect_uri
    return flow


@router.get("/google")
async def google_login():
    if not settings.google_client_id:
        return JSONResponse(
            status_code=503,
            content={"error": "Google OAuth not configured. Set GOOGLE_CLIENT_ID in .env"},
        )
    flow = _build_flow()
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    return RedirectResponse(auth_url)


@router.get("/google/callback")
async def google_callback(request: Request):
    """
    Exchange the authorization code for OAuth tokens and store them
    in the PostgreSQL `users` table (google_tokens JSONB column).

    The user row is upserted by email so re-auth refreshes the stored token.
    """
    code = request.query_params.get("code")
    error = request.query_params.get("error")

    if error:
        log.warning("google_oauth_error", error=error)
        return JSONResponse(status_code=400, content={"error": f"Google OAuth error: {error}"})

    if not code:
        return JSONResponse(status_code=400, content={"error": "Missing 'code' parameter in callback."})

    if not settings.google_client_id:
        return JSONResponse(
            status_code=503,
            content={"error": "Google OAuth not configured on this server."},
        )

    try:
        flow = _build_flow()
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Build a serialisable token dict to persist
        token_data = {
            "token": credentials.token,
            "refresh_token": credentials.refresh_token,
            "token_uri": credentials.token_uri,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "scopes": list(credentials.scopes) if credentials.scopes else [],
        }

        # Fetch basic profile info to identify/create the user row
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=10.0) as http:
            profile_resp = await http.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
        profile = profile_resp.json()
        email = profile.get("email", "")
        name = profile.get("name", "")

        # Upsert the user row and store the token blob
        from db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO users (email, name, google_tokens)
                VALUES ($1, $2, $3::jsonb)
                ON CONFLICT (email) DO UPDATE
                    SET google_tokens = EXCLUDED.google_tokens,
                        name          = EXCLUDED.name,
                        updated_at    = NOW()
                """,
                email,
                name,
                json.dumps(token_data),
            )

        log.info("google_oauth_success", email=email)
        return JSONResponse(
            status_code=200,
            content={
                "message": "Google account connected successfully.",
                "email": email,
                "name": name,
                "scopes": token_data["scopes"],
            },
        )

    except Exception as exc:
        log.error("google_oauth_callback_failed", error=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to complete Google OAuth: {exc}"},
        )
