"""
Auth router — Google OAuth for calendar integration
"""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from google_auth_oauthlib.flow import Flow

from config import settings

router = APIRouter()

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
]


@router.get("/google")
async def google_login():
    if not settings.google_client_id:
        return {"error": "Google OAuth not configured. Set GOOGLE_CLIENT_ID in .env"}
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uris": [settings.google_redirect_uri if hasattr(settings, 'google_redirect_uri') else "http://localhost:8000/auth/google/callback"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    flow.redirect_uri = "http://localhost:8000/auth/google/callback"
    auth_url, _ = flow.authorization_url(prompt="consent")
    return RedirectResponse(auth_url)


@router.get("/google/callback")
async def google_callback(request: Request):
    return {"message": "Google auth callback — implement token storage here", "params": dict(request.query_params)}
