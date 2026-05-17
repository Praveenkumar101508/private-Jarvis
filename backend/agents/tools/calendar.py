"""
Google Calendar tool — fetch upcoming events
"""
from datetime import datetime, timedelta, timezone


async def get_calendar_events(days_ahead: int = 7) -> list[dict]:
    """Fetch upcoming calendar events. Returns mock data if Google OAuth not configured."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials
        # TODO: load credentials from database/session
        # This is a placeholder — implement OAuth token retrieval
        return [{"error": "Google Calendar OAuth not yet configured. Please connect your Google account at /auth/google"}]
    except Exception as exc:
        return [{"error": str(exc)}]


async def create_event(title: str, start: datetime, end: datetime, description: str = "") -> dict:
    """Create a calendar event."""
    return {
        "status": "not_implemented",
        "message": "Calendar write access requires OAuth setup. Visit /auth/google",
    }
