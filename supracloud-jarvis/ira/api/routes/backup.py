"""
Backup & Restore API — admin-only endpoints for database management.

GET  /backup/list                → list available backup files with metadata
GET  /backup/download/{filename} → download a specific .sql.gz backup
POST /backup/create              → trigger an immediate backup now
POST /backup/restore             → restore from uploaded .sql.gz file (DANGER)

All endpoints require admin authentication (403 for non-admin users).
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from api.middleware.auth import require_auth
from config import get_settings
from worker.backup import BACKUP_DIR, list_backups, restore_from_file, run_database_backup

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

    path = BACKUP_DIR / filename
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
):
    """
    Restore the database from an uploaded .sql.gz backup file.

    WARNING: This applies the SQL dump on top of the current database.
    For a full reset, stop the API, drop and recreate the DB, then restore.
    """
    if not file.filename or not file.filename.endswith(".sql.gz"):
        raise HTTPException(status_code=400, detail="Upload must be a .sql.gz backup file")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = BACKUP_DIR / f"restore_upload_{file.filename}"
    try:
        content = await file.read()
        if len(content) == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        tmp_path.write_bytes(content)

        success, message = await restore_from_file(tmp_path)
        if not success:
            raise HTTPException(status_code=500, detail=message)

        logger.info(f"Database restored from upload: {file.filename} by admin")
        return {"status": "restored", "message": message}
    finally:
        tmp_path.unlink(missing_ok=True)
