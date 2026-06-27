"""Phase 3 — local-first notes: CRUD round-trip, path-traversal safety, and the
destructive delete behind the approval guardrail."""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio

from actions import notes as notes_store
import api.routes.notes as notes_route
from api.routes.notes import delete_note


class _Cfg:
    def __init__(self, d):
        self.notes_dir = str(d)


def test_create_get_list_search_roundtrip(tmp_path):
    cfg = _Cfg(tmp_path)
    created = notes_store.create_note("Quantum ideas", "qubits and coherence", ["physics"], cfg=cfg)
    assert created["status"] == "created"
    nid = created["id"]

    got = notes_store.get_note(nid, cfg=cfg)
    assert got["title"] == "Quantum ideas"
    assert "qubits" in got["body"]
    assert got["tags"] == ["physics"]

    listing = notes_store.list_notes(cfg=cfg)
    assert any(n["id"] == nid for n in listing)

    assert any(n["id"] == nid for n in notes_store.search_notes("coherence", cfg=cfg))
    assert notes_store.search_notes("nonexistent-term", cfg=cfg) == []


def test_delete_removes_note(tmp_path):
    cfg = _Cfg(tmp_path)
    nid = notes_store.create_note("temp", "x", cfg=cfg)["id"]
    assert notes_store.delete_note(nid, cfg=cfg)["status"] == "deleted"
    assert notes_store.get_note(nid, cfg=cfg) is None


def test_path_traversal_ids_are_rejected(tmp_path):
    cfg = _Cfg(tmp_path)
    for bad in ("../etc/passwd", "a/b", "..", "foo.md", "x\\y", "/abs"):
        assert notes_store.is_valid_id(bad) is False
        assert notes_store.get_note(bad, cfg=cfg) is None
        assert notes_store.delete_note(bad, cfg=cfg)["status"] == "error"


def test_missing_dir_failsoft(tmp_path):
    cfg = _Cfg(tmp_path / "does-not-exist-yet")
    assert notes_store.list_notes(cfg=cfg) == []
    assert notes_store.search_notes("x", cfg=cfg) == []
    assert notes_store.get_note("whatever", cfg=cfg) is None


# ── the destructive delete is gated at the route ─────────────────────────────

def test_route_delete_requires_confirmation(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings",
                        lambda: type("C", (), {"ira_admin_username": "owner"})())
    calls: list = []

    def fake_delete(nid):
        calls.append(nid)
        return {"status": "deleted", "id": nid}

    monkeypatch.setattr(notes_route.notes_store, "delete_note", fake_delete)

    # No token → a draft is staged, nothing is deleted.
    draft = asyncio.run(delete_note("some-note", confirm_token=None, _user="owner"))
    assert draft["status"] == "confirmation_required"
    assert calls == []

    # Valid token → the delete runs.
    res = asyncio.run(delete_note("some-note", confirm_token=draft["token"], _user="owner"))
    assert res["status"] == "deleted"
    assert calls == ["some-note"]


def test_route_delete_forbidden_for_non_owner(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings",
                        lambda: type("C", (), {"ira_admin_username": "owner"})())
    import fastapi
    try:
        asyncio.run(delete_note("x", confirm_token=None, _user="intruder"))
        assert False, "should have raised"
    except fastapi.HTTPException as exc:
        assert exc.status_code == 403
