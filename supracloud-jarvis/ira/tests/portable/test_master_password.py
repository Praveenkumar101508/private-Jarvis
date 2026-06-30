"""V2·Phase 2 — master-password setup, verify, and failed-attempt lockout."""
import sys
from pathlib import Path

import pytest

# portable/ lives beside ira/ (supracloud-jarvis/portable)
_PORTABLE = Path(__file__).resolve().parents[3] / "portable"
sys.path.insert(0, str(_PORTABLE))

from master_password import (  # noqa: E402
    MasterPasswordError,
    MasterPasswordStore,
    require_master_password,
)


class _Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t
    def advance(self, s): self.t += s


def _store(tmp_path, **kw):
    return MasterPasswordStore(tmp_path, **kw)


def test_setup_then_verify(tmp_path):
    s = _store(tmp_path)
    assert s.is_initialized() is False
    s.setup("hunter2-strong")
    assert s.is_initialized() is True
    assert s.verify("hunter2-strong").ok is True
    assert s.verify("wrong-password").ok is False


def test_stored_record_is_encrypted_not_plaintext(tmp_path):
    s = _store(tmp_path)
    s.setup("hunter2-strong")
    blob = (tmp_path / "master.enc").read_bytes()
    assert b"hunter2-strong" not in blob          # password never stored
    assert b'"hash"' not in blob                  # JSON is encrypted, not plaintext
    assert b"$2b$" not in blob                     # the bcrypt hash is not in the clear


def test_setup_rejects_short_password(tmp_path):
    with pytest.raises(MasterPasswordError):
        _store(tmp_path).setup("short")


def test_setup_refuses_overwrite_without_force(tmp_path):
    s = _store(tmp_path)
    s.setup("hunter2-strong")
    with pytest.raises(MasterPasswordError):
        s.setup("another-strong-one")
    s.setup("another-strong-one", force=True)     # force resets
    assert s.verify("another-strong-one").ok is True


def test_lockout_after_max_attempts(tmp_path):
    clock = _Clock()
    s = _store(tmp_path, max_attempts=3, cooldown_seconds=60, now=clock)
    s.setup("hunter2-strong")

    assert s.verify("nope").remaining_attempts == 2
    assert s.verify("nope").remaining_attempts == 1
    locked = s.verify("nope")
    assert locked.ok is False and locked.locked is True
    assert locked.retry_after_seconds == 60

    # even the CORRECT password is refused while locked
    assert s.verify("hunter2-strong").locked is True

    # after the cooldown, the correct password works and resets the counter
    clock.advance(61)
    ok = s.verify("hunter2-strong")
    assert ok.ok is True
    assert s.verify("nope").remaining_attempts == 2  # counter was reset on success


def test_require_master_password_gate(tmp_path):
    s = _store(tmp_path)
    with pytest.raises(MasterPasswordError):
        require_master_password(s, "anything")  # not initialized → refuse to boot
    s.setup("hunter2-strong")
    require_master_password(s, "hunter2-strong")  # ok → no raise
    with pytest.raises(MasterPasswordError):
        require_master_password(s, "wrong")
