"""
Persistent file storage — upload, list, download, delete.  # Feat P25

All endpoints are scoped to the authenticated user — a user can only see,
download, or delete their own files.  Server-side storage is under
/data/files/<user_id>/<uuid> inside the files_data Docker volume.

Security:
  - User scope enforced on every read/delete (404 not 403 to avoid id enumeration)
  - Filenames sanitised via pathlib.Path.name (strips directory components)
  - Paths never come from the client — only the UUID row id is trusted
  - File size capped at 50 MB via read_with_size_cap
"""
from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse

from api.middleware.auth import require_auth, is_owner
from utils.approval import owner_gated_action
from utils.db import acquire
from utils.file_utils import read_with_size_cap

router = APIRouter(prefix="/files", tags=["files"])

_FILES_ROOT = Path(os.environ.get("FILES_DATA_DIR", "/data/files"))
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def _user_dir(user_id: str) -> Path:
    root = _FILES_ROOT.resolve()
    d = (root / user_id).resolve()
    # Fix P30: is_relative_to avoids the str.startswith prefix bypass
    # (e.g. /data/files-evil starts with /data/files but is not relative to it)
    if not d.is_relative_to(root):
        raise ValueError("Path traversal attempt")
    return d


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    _user: str = Depends(require_auth),
):
    # Writing files is a side effect: restrict to the verified owner (fail-closed).
    # (The two-step draft/confirm flow doesn't fit a streamed multipart upload, so
    # writes are owner-gated only; deletes below get the full confirm flow.)
    if not is_owner(_user):
        raise HTTPException(status_code=403, detail="Uploading files is restricted to the verified owner.")
    content = await read_with_size_cap(file, max_bytes=_MAX_BYTES)
    safe_name = Path(file.filename or "upload").name  # strip any directory
    file_id = str(uuid.uuid4())
    mime = file.content_type or "application/octet-stream"
    sha256 = hashlib.sha256(content).hexdigest()

    dest_dir = _user_dir(_user)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / file_id
    dest.write_bytes(content)

    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO files (id, user_id, filename, mime_type, size_bytes, storage_path, sha256)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            file_id, _user, safe_name, mime, len(content), str(dest), sha256,
        )

    return {"id": file_id, "filename": safe_name, "size_bytes": len(content), "sha256": sha256}


# ── List ──────────────────────────────────────────────────────────────────────

@router.get("")
async def list_files(_user: str = Depends(require_auth)):
    async with acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, filename, mime_type, size_bytes, sha256, created_at "
            "FROM files WHERE user_id=$1 ORDER BY created_at DESC",
            _user,
        )
    return [dict(r) for r in rows]


# ── Download ──────────────────────────────────────────────────────────────────

@router.get("/{file_id}")
async def download_file(file_id: str, _user: str = Depends(require_auth)):
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT filename, mime_type, storage_path FROM files WHERE id=$1 AND user_id=$2",
            file_id, _user,
        )
    if not row:
        raise HTTPException(status_code=404, detail="File not found")
    path = Path(row["storage_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File data missing — contact support")
    return FileResponse(path=str(path), filename=row["filename"], media_type=row["mime_type"])


# ── Delete ────────────────────────────────────────────────────────────────────

@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    confirm_token: str | None = Query(None, description="Approval token; omit to receive a draft"),
    _user: str = Depends(require_auth),
):
    """Delete a file — owner-gated and confirmation-gated (destructive)."""

    async def _do():
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT storage_path FROM files WHERE id=$1 AND user_id=$2",
                file_id, _user,
            )
        if not row:
            raise HTTPException(status_code=404, detail="File not found")
        async with acquire() as conn:
            await conn.execute("DELETE FROM files WHERE id=$1 AND user_id=$2", file_id, _user)
        try:
            Path(row["storage_path"]).unlink(missing_ok=True)
        except OSError:
            pass  # row is gone; best-effort disk cleanup
        return {"deleted": True, "file_id": file_id}

    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="delete_file", preview=f"Delete file {file_id}",
        execute=_do, confirm_token=confirm_token,
    )
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]
    return outcome  # confirmation_required
