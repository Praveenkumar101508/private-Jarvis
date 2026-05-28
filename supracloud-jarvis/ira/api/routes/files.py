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

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse

from api.middleware.auth import require_auth
from utils.db import acquire
from utils.file_utils import read_with_size_cap

router = APIRouter(prefix="/files", tags=["files"])

_FILES_ROOT = Path(os.environ.get("FILES_DATA_DIR", "/data/files"))
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def _user_dir(user_id: str) -> Path:
    d = (_FILES_ROOT / user_id).resolve()
    if not str(d).startswith(str(_FILES_ROOT.resolve())):
        raise ValueError("Path traversal attempt")
    return d


# ── Upload ────────────────────────────────────────────────────────────────────

@router.post("/upload", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    _user: str = Depends(require_auth),
):
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

@router.delete("/{file_id}", status_code=204)
async def delete_file(file_id: str, _user: str = Depends(require_auth)):
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
