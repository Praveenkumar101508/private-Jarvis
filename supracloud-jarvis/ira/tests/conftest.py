import sys
import types
import pytest

# ---------------------------------------------------------------------------
# Lightweight stubs for modules that require native extensions or network
# connections that are not present in the CI / unit-test environment.
# ---------------------------------------------------------------------------

def _stub(name: str, **attrs):
    """Insert a minimal stub module into sys.modules."""
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


# asyncpg — PostgreSQL client (not installed in test env)
_asyncpg = _stub("asyncpg")
_asyncpg.Pool = object
_asyncpg.Connection = object


# utils.db — wraps asyncpg; replaced entirely by test patches
_db = _stub("utils.db", acquire=None)


# worker.notifier — Telegram/email/WebSocket; replaced by test patches
_stub("worker.notifier", notify=None)

# worker.backup — not exercised by webhook tests
_stub("worker.backup",
      list_backups=None,
      restore_from_file=None,
      run_database_backup=None)

# sentence_transformers — ML library not in test env
_stub("sentence_transformers")

# uvloop — optional performance lib
_stub("uvloop")

# livekit.api — only available inside the Docker image
_livekit = _stub("livekit")
_livekit_api = _stub("livekit.api")
_livekit.api = _livekit_api
_livekit_api.WebhookReceiver = object
