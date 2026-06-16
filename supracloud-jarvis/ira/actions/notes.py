"""
ira/actions/notes.py — local-first, on-disk markdown notes.

Notes live as plain ``.md`` files under ``settings.notes_dir`` (no database, no
cloud) so they are trivially portable, greppable, and owned by the user. Each note
carries a small frontmatter header (id, title, created, tags).

Read/create/search are non-destructive and run directly. The only destructive
operation, :func:`delete_note`, is exposed through the approval guardrail at the
route layer (owner + explicit confirmation) — this module never deletes silently
and validates every id against path traversal.

Every function fails soft: a missing directory, unreadable file, or bad id returns
a clear status dict instead of raising, so a chat turn is never broken.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config import get_settings

logger = logging.getLogger("ira.actions.notes")

# A note id is a lowercase slug — no slashes, dots, or anything that could escape
# the notes directory. Generated ids match this; supplied ids are validated.
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


def _notes_dir(cfg) -> Path:
    return Path((cfg or get_settings()).notes_dir)


def _slugify(title: str) -> str:
    slug = _SLUG_RE.sub("-", (title or "").lower()).strip("-")
    return slug[:60] or "note"


def is_valid_id(note_id: str) -> bool:
    """True only for safe ids — the path-traversal guard for every file op."""
    return bool(_ID_RE.match(note_id or ""))


def _note_path(note_id: str, cfg) -> Optional[Path]:
    """Resolve a note id to a path, refusing anything that escapes the notes dir."""
    if not is_valid_id(note_id):
        return None
    base = _notes_dir(cfg).resolve()
    path = (base / f"{note_id}.md").resolve()
    # Defence in depth: the resolved path must stay inside the notes dir.
    if base != path.parent:
        return None
    return path


def _render(note_id: str, title: str, body: str, created: str, tags: list[str]) -> str:
    return (
        "---\n"
        f"id: {note_id}\n"
        f"title: {title}\n"
        f"created: {created}\n"
        f"tags: {', '.join(tags)}\n"
        "---\n"
        f"{body}\n"
    )


def _parse(path: Path) -> Optional[dict]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — fail soft
        logger.warning("failed to read note %s: %s", path, exc)
        return None
    meta = {"id": path.stem, "title": path.stem, "created": "", "tags": []}
    body = text
    m = _FRONTMATTER_RE.match(text)
    if m:
        header, body = m.group(1), m.group(2)
        for line in header.splitlines():
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip()
            if key == "tags":
                meta["tags"] = [t.strip() for t in val.split(",") if t.strip()]
            elif key in meta:
                meta[key] = val
    meta["body"] = body.strip()
    return meta


def create_note(title: str, body: str = "", tags: Optional[list[str]] = None, cfg=None) -> dict:
    """Create a note on disk. Returns its metadata (never raises)."""
    tags = tags or []
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Unique id: slug + timestamp suffix, so repeated titles don't collide.
    note_id = f"{_slugify(title)}-{int(datetime.now(timezone.utc).timestamp())}"
    if not is_valid_id(note_id):  # paranoia — slugify already guarantees this
        note_id = f"note-{int(datetime.now(timezone.utc).timestamp())}"
    try:
        base = _notes_dir(cfg)
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{note_id}.md"
        path.write_text(_render(note_id, title, body, created, tags), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"Could not create note: {exc}"}
    return {"status": "created", "id": note_id, "title": title, "created": created, "tags": tags}


def list_notes(cfg=None) -> list[dict]:
    """List note metadata (no bodies), newest first. Empty list if none."""
    base = _notes_dir(cfg)
    if not base.exists():
        return []
    out = []
    for path in base.glob("*.md"):
        meta = _parse(path)
        if meta:
            out.append({k: meta[k] for k in ("id", "title", "created", "tags")})
    out.sort(key=lambda n: n.get("created", ""), reverse=True)
    return out


def get_note(note_id: str, cfg=None) -> Optional[dict]:
    """Return a single note (with body), or None if missing / bad id."""
    path = _note_path(note_id, cfg)
    if path is None or not path.exists():
        return None
    return _parse(path)


def search_notes(query: str, cfg=None) -> list[dict]:
    """Case-insensitive substring search over title, body and tags."""
    q = (query or "").strip().lower()
    if not q:
        return list_notes(cfg)
    base = _notes_dir(cfg)
    if not base.exists():
        return []
    hits = []
    for path in base.glob("*.md"):
        meta = _parse(path)
        if not meta:
            continue
        haystack = " ".join([meta["title"], meta["body"], " ".join(meta["tags"])]).lower()
        if q in haystack:
            hits.append({k: meta[k] for k in ("id", "title", "created", "tags")})
    hits.sort(key=lambda n: n.get("created", ""), reverse=True)
    return hits


def delete_note(note_id: str, cfg=None) -> dict:
    """Delete a note. DESTRUCTIVE — callers must gate this behind approval."""
    path = _note_path(note_id, cfg)
    if path is None:
        return {"status": "error", "message": f"Invalid note id {note_id!r}."}
    if not path.exists():
        return {"status": "not_found", "id": note_id}
    try:
        path.unlink()
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"Could not delete note: {exc}"}
    return {"status": "deleted", "id": note_id}


__all__ = [
    "is_valid_id", "create_note", "list_notes", "get_note", "search_notes", "delete_note",
]
