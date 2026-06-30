"""
portable/master_password.py — IRA portable-demo master-password gate (V2·Phase 2).

Security properties:
  * Hash: bcrypt (cost 12) over a SHA-256 pre-hash of the password, so passwords
    longer than bcrypt's 72-byte limit are handled safely.
  * At rest: the record (hash + lockout state) is stored ONLY as a Fernet-encrypted
    blob — never plaintext. The Fernet key lives in a sibling key file written 0600.
  * No echo / no logging of the secret: this module never logs or returns the
    password; the CLIs read it with getpass (no echo).
  * Lockout: after ``max_attempts`` consecutive failures the gate locks for a
    cooldown that escalates with each further failure; a correct password resets it.

The core is a plain class taking a directory and an injectable clock so it is fully
unit-testable without prompts or real time.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("ira.portable.master_password")

_BCRYPT_ROUNDS = 12
_DEFAULT_MAX_ATTEMPTS = 5
_DEFAULT_COOLDOWN_S = 60


def _prehash(password: str) -> bytes:
    """SHA-256 → base64 so bcrypt's 72-byte cap never truncates a long passphrase."""
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    locked: bool = False
    remaining_attempts: int = 0
    retry_after_seconds: int = 0
    message: str = ""


class MasterPasswordError(RuntimeError):
    pass


class MasterPasswordStore:
    """Encrypted-at-rest master-password store with lockout."""

    def __init__(
        self,
        directory: str | os.PathLike,
        *,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
        cooldown_seconds: int = _DEFAULT_COOLDOWN_S,
        now: Optional[Callable[[], float]] = None,
    ) -> None:
        self.dir = Path(directory)
        self.enc_path = self.dir / "master.enc"
        self.key_path = self.dir / "master.key"
        self.max_attempts = max_attempts
        self.cooldown_seconds = cooldown_seconds
        import time as _time

        self._now = now or _time.time

    # ── key + record I/O ────────────────────────────────────────────────────
    def _fernet(self) -> Fernet:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
        else:
            self.dir.mkdir(parents=True, exist_ok=True)
            key = Fernet.generate_key()
            self.key_path.write_bytes(key)
            _chmod_600(self.key_path)
        return Fernet(key)

    def _read(self) -> Optional[dict]:
        if not self.enc_path.exists():
            return None
        try:
            raw = self._fernet().decrypt(self.enc_path.read_bytes())
        except (InvalidToken, ValueError) as exc:
            raise MasterPasswordError("master password record is unreadable/corrupt") from exc
        return json.loads(raw.decode("utf-8"))

    def _write(self, record: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        blob = self._fernet().encrypt(json.dumps(record).encode("utf-8"))
        self.enc_path.write_bytes(blob)
        _chmod_600(self.enc_path)

    # ── public API ──────────────────────────────────────────────────────────
    def is_initialized(self) -> bool:
        return self.enc_path.exists()

    def setup(self, password: str, *, force: bool = False) -> None:
        if not password or len(password) < 8:
            raise MasterPasswordError("master password must be at least 8 characters")
        if self.is_initialized() and not force:
            raise MasterPasswordError("master password already set (use force to reset)")
        hashed = bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
        self._write({
            "version": 1,
            "hash": hashed.decode("ascii"),
            "failed_attempts": 0,
            "locked_until": 0.0,
        })
        logger.info("master password initialized")  # never logs the password

    def verify(self, password: str) -> VerifyResult:
        record = self._read()
        if record is None:
            return VerifyResult(ok=False, message="no master password is set")

        now = self._now()
        locked_until = float(record.get("locked_until", 0.0))
        if now < locked_until:
            return VerifyResult(
                ok=False, locked=True,
                retry_after_seconds=int(locked_until - now) + 1,
                message="locked due to repeated failures",
            )

        if bcrypt.checkpw(_prehash(password), record["hash"].encode("ascii")):
            record["failed_attempts"] = 0
            record["locked_until"] = 0.0
            self._write(record)
            logger.info("master password verified")
            return VerifyResult(ok=True, message="verified")

        # wrong password — count it and maybe lock
        attempts = int(record.get("failed_attempts", 0)) + 1
        record["failed_attempts"] = attempts
        result: VerifyResult
        if attempts >= self.max_attempts:
            over = attempts - self.max_attempts + 1
            lock_for = self.cooldown_seconds * over
            record["locked_until"] = now + lock_for
            result = VerifyResult(
                ok=False, locked=True, retry_after_seconds=lock_for,
                message=f"locked for {lock_for}s after {attempts} failed attempts",
            )
            logger.warning("master password locked after %d failed attempts", attempts)
        else:
            result = VerifyResult(
                ok=False, remaining_attempts=self.max_attempts - attempts,
                message="incorrect master password",
            )
            logger.warning("master password attempt failed (%d/%d)", attempts, self.max_attempts)
        self._write(record)
        return result


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):  # pragma: no cover - e.g. Windows FS
        pass


def require_master_password(store: MasterPasswordStore, password: str) -> None:
    """Startup gate: raise unless the password verifies. The launcher calls this and
    refuses to boot on a raised error."""
    if not store.is_initialized():
        raise MasterPasswordError(
            "no master password is set — run portable/setup_master_password.py first"
        )
    result = store.verify(password)
    if not result.ok:
        raise MasterPasswordError(result.message)
