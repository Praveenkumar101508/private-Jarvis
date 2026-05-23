"""
IRA Database Backup — nightly pg_dump + one-click restore.

Runs at 03:00 UTC daily via APScheduler.
Saves compressed SQL dumps to /backups/ (Docker volume: backup_data).
Keeps the last 7 backups; older ones are pruned automatically.

Restore: POST /api/v1/backup/restore (admin only) — uploads a .sql.gz file
and applies it via psql.  Use with caution: overwrites current data.
"""

from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from config import get_settings

logger = logging.getLogger("ira.backup")

BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
KEEP_BACKUPS = int(os.getenv("BACKUP_KEEP", "7"))


def _backup_filename(ts: datetime) -> str:
    return f"ira_backup_{ts.strftime('%Y%m%d_%H%M%S')}.sql.gz"


async def run_database_backup() -> Path | None:
    """
    Run pg_dump, gzip the output, and save to BACKUP_DIR.
    Returns the Path to the created file, or None on failure.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    cfg = get_settings()
    ts = datetime.now(timezone.utc)
    out_path = BACKUP_DIR / _backup_filename(ts)

    env = {**os.environ, "PGPASSWORD": cfg.postgres_password}

    cmd = [
        "pg_dump",
        "-h", cfg.postgres_host,
        "-p", str(cfg.postgres_port),
        "-U", cfg.postgres_user,
        "-d", cfg.postgres_db,
        "--no-password",
        "--format=plain",
    ]

    try:
        logger.info(f"Starting database backup → {out_path.name}")
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

        if proc.returncode != 0:
            logger.error(f"pg_dump failed (exit {proc.returncode}): {stderr.decode()[:400]}")
            return None

        # Write compressed backup
        with gzip.open(out_path, "wb", compresslevel=6) as f:
            f.write(stdout)

        size_mb = out_path.stat().st_size / 1024 / 1024
        logger.info(f"Backup complete: {out_path.name} ({size_mb:.1f} MB)")

        _prune_old_backups()
        return out_path

    except asyncio.TimeoutError:
        logger.error("pg_dump timed out after 10 minutes")
        return None
    except FileNotFoundError:
        logger.error("pg_dump not found — install postgresql-client in Dockerfile.worker")
        return None
    except Exception as e:
        logger.error(f"Backup failed: {e}")
        return None


def _prune_old_backups() -> None:
    """Delete backups beyond the retention limit (newest KEEP_BACKUPS kept)."""
    backups = sorted(BACKUP_DIR.glob("ira_backup_*.sql.gz"), reverse=True)
    for old in backups[KEEP_BACKUPS:]:
        old.unlink(missing_ok=True)
        logger.info(f"Pruned old backup: {old.name}")


def list_backups() -> list[dict]:
    """Return metadata for all available backups, newest first."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("ira_backup_*.sql.gz"), reverse=True)
    result = []
    for p in backups:
        stat = p.stat()
        result.append({
            "filename": p.name,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
        })
    return result


async def restore_from_file(gz_path: Path) -> tuple[bool, str]:
    """
    Restore the database from a .sql.gz backup file.
    Returns (success, message).
    """
    cfg = get_settings()
    env = {**os.environ, "PGPASSWORD": cfg.postgres_password}
    ts = datetime.now(timezone.utc)
    temp_sql = BACKUP_DIR / f"restore_temp_{ts.strftime('%Y%m%d_%H%M%S')}.sql"

    try:
        # Decompress to a temporary plain SQL file
        with gzip.open(gz_path, "rb") as fin, open(temp_sql, "wb") as fout:
            shutil.copyfileobj(fin, fout)

        cmd = [
            "psql",
            "-h", cfg.postgres_host,
            "-p", str(cfg.postgres_port),
            "-U", cfg.postgres_user,
            "-d", cfg.postgres_db,
            "--no-password",
            "-f", str(temp_sql),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600)

        if proc.returncode != 0:
            return False, f"psql restore failed: {stderr.decode()[:400]}"

        return True, f"Restore complete from {gz_path.name}"

    except asyncio.TimeoutError:
        return False, "Restore timed out after 10 minutes"
    except Exception as e:
        return False, f"Restore error: {e}"
    finally:
        temp_sql.unlink(missing_ok=True)
