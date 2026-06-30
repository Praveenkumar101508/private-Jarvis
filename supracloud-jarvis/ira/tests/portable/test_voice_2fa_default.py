"""V2·Phase 5 — portable voice 2FA is OFF by default (optional second factor only)."""
import pytest

_INFRA = {
    "IRA_SECRET_KEY": "ci-secret",
    "IRA_ADMIN_PASSWORD": "ci-admin",
    "POSTGRES_PASSWORD": "ci-db",
    "REDIS_PASSWORD": "ci-redis",
}


def _clear():
    from config import get_settings

    get_settings.cache_clear()


def test_voice_2fa_off_by_default():
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("IRA_PORTABLE_VOICE_2FA", raising=False)
        for k, v in _INFRA.items():
            mp.setenv(k, v)
        _clear()
        from config import get_settings

        assert get_settings().ira_portable_voice_2fa is False
    _clear()


def test_voice_2fa_opt_in():
    with pytest.MonkeyPatch.context() as mp:
        for k, v in _INFRA.items():
            mp.setenv(k, v)
        mp.setenv("IRA_PORTABLE_VOICE_2FA", "true")
        _clear()
        from config import get_settings

        assert get_settings().ira_portable_voice_2fa is True
    _clear()
