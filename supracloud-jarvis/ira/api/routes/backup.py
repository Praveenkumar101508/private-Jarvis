"""
Backup & Restore API — admin-only endpoints for database management.

GET  /backup/list                → list available backup files with metadata
GET  /backup/download/{filename} → download a specific .sql.gz backup
POST /backup/create              → trigger an immediate backup now
POST /backup/restore             → restore from uploaded .sql.gz file (DANGER)

All endpoints require admin authentication (403 for non-admin users).
"""

from __future__ import annotations

import gzip
import hashlib
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.middleware.auth import require_auth
from config import get_settings
from worker.backup import list_backups, restore_from_file, run_database_backup

router = APIRouter(prefix="/backup", tags=["backup"])
logger = logging.getLogger("ira.backup_api")


def _require_admin(username: str = Depends(require_auth)) -> str:
    cfg = get_settings()
    if username != cfg.ira_admin_username:
        raise HTTPException(status_code=403, detail="Admin access required for backup operations")
    return username


@router.get("/list")
async def list_available_backups(_user: str = Depends(_require_admin)):
    """Return metadata for all available backups, newest first."""
    return {"backups": list_backups()}


@router.get("/download/{filename}")
async def download_backup(filename: str, _user: str = Depends(_require_admin)):
    """Download a specific backup file by filename."""
    # Prevent path traversal
    if any(c in filename for c in ("/", "\\", "..")):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filename.endswith(".sql.gz"):
        raise HTTPException(status_code=400, detail="Only .sql.gz backups are available")

    path = Path(get_settings().backup_dir) / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Backup not found: {filename}")

    return FileResponse(
        path=str(path),
        media_type="application/gzip",
        filename=filename,
    )


@router.post("/create")
async def create_backup(_user: str = Depends(_require_admin)):
    """Trigger an immediate database backup. Returns metadata of the created file."""
    path = await run_database_backup()
    if not path:
        raise HTTPException(
            status_code=500,
            detail="Backup failed — check worker logs (is pg_dump installed?)",
        )
    stat = path.stat()
    return {
        "status": "created",
        "filename": path.name,
        "size_mb": round(stat.st_size / 1024 / 1024, 2),
    }


@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(..., description="A .sql.gz backup file to restore from"),
    _user: str = Depends(_require_admin),
    x_restore_confirm: str | None = Header(None, alias="X-Restore-Confirm"),
):
    """
    Restore the database from an uploaded .sql.gz backup file.

    Requires header: X-Restore-Confirm: yes
    WARNING: This applies the SQL dump on top of the current database.
    For a full reset, stop the API, drop and recreate the DB, then restore.
    """
    if x_restore_confirm != "yes":
        raise HTTPException(
            status_code=400,
            detail="Missing confirmation header. Send 'X-Restore-Confirm: yes' to proceed.",
        )

    if not file.filename or not file.filename.endswith(".sql.gz"):
        raise HTTPException(status_code=400, detail="Upload must be a .sql.gz backup file")

    backup_dir = Path(get_settings().backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    # Use a UUID-based name — never trust the client-supplied filename
    tmp_path = backup_dir / f"restore_{uuid.uuid4()}.sql.gz"
    try:
        from utils.file_utils import read_with_size_cap
        content = await read_with_size_cap(file, max_bytes=500 * 1024 * 1024)  # 500 MB cap
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        # Verify gzip integrity before touching the live database
        try:
            with gzip.open(tmp_path.__class__(tmp_path), "rb") as _gz:
                pass  # Use the bytes directly — open from memory
            # Validate via in-memory check
            import io
            with gzip.GzipFile(fileobj=io.BytesIO(content)) as _gz:
                _gz.read(512)  # Read a small chunk to verify the gzip header/stream
        except Exception as gz_err:
            raise HTTPException(status_code=400, detail=f"Invalid or corrupt .sql.gz file: {gz_err}")

        sha256 = hashlib.sha256(content).hexdigest()
        tmp_path.write_bytes(content)

        logger.warning(
            "RESTORE initiated by admin: file=%s size_bytes=%d sha256=%s",
            file.filename, len(content), sha256,
        )

        # Take a pre-restore snapshot so we can recover if the restore goes wrong
        pre_restore_path = await run_database_backup()
        if pre_restore_path:
            logger.info("Pre-restore snapshot created: %s", pre_restore_path.name)
        else:
            logger.warning("Pre-restore snapshot failed — proceeding anyway")

        success, message = await restore_from_file(tmp_path)
        if not success:
            raise HTTPException(status_code=500, detail=message)

        logger.warning(
            "RESTORE complete: file=%s sha256=%s pre_restore_snapshot=%s",
            file.filename, sha256,
            pre_restore_path.name if pre_restore_path else "none",
        )
        return {
            "status": "restored",
            "message": message,
            "sha256": sha256,
            "pre_restore_snapshot": pre_restore_path.name if pre_restore_path else None,
        }
    finally:
        tmp_path.unlink(missing_ok=True)
