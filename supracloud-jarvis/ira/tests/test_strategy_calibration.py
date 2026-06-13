"""Phase 6 — strategy calibration loop (sovereign, learns from the owner's own outcomes).

Covers (all runnable in the lightweight CI env — no live Postgres):
  * pure calibration math: domain inference, Brier, offset derivation + shrinkage, apply;
  * the store flow persist -> record_outcome -> recompute -> load via a FakeConn;
  * run_strategy applies a stored per-domain adjustment and reports "calibrated on N";
  * the /strategy/outcome + /strategy/predictions endpoints (auth overridden).
"""
import os

# Settings require these; prime them before importing config-backed code.
for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import agents.strategy_mode as sm
import agents.strategy_calibration as cal
from agents.strategy_mode import run_strategy


# ── A tenant-free, stateful asyncpg stand-in for the strategy_calibration queries ──

class FakeConn:
    """Understands this module's query shapes; stores rows in-memory so persist ->
    record -> recompute -> load round-trips without a live Postgres."""

    def __init__(self):
        self.predictions: dict[str, dict] = {}   # id -> row
        self.calibration: dict[str, dict] = {}    # domain -> row

    async def fetchrow(self, sql, *args):
        if "INSERT INTO strategy_predictions" in sql:
            rid = str(uuid.uuid4())
            self.predictions[rid] = {
                "id": rid, "question": args[0], "domain": args[1], "option_name": args[2],
                "success_probability": args[3], "risk": args[4], "effort": args[5],
                "utility": args[6], "outcome": None, "outcome_notes": None,
                "created_at": datetime.now(timezone.utc),
            }
            return {"id": rid}
        if "UPDATE strategy_predictions" in sql:
            pid = str(args[0])
            row = self.predictions.get(pid)
            if row is None:
                return None
            row["outcome"], row["outcome_notes"] = args[1], args[2]
            row["resolved_at"] = datetime.now(timezone.utc)
            return {"id": pid, "domain": row["domain"],
                    "option_name": row["option_name"], "outcome": row["outcome"]}
        if "FROM strategy_calibration" in sql:
            return self.calibration.get(args[0])
        return None

    async def fetch(self, sql, *args):
        if "FROM strategy_predictions" in sql and "outcome IS NOT NULL" in sql:
            dom = args[0]
            return [r for r in self.predictions.values()
                    if r["domain"] == dom and r["outcome"] is not None]
        if "FROM strategy_predictions" in sql:
            rows = sorted(self.predictions.values(), key=lambda r: r["created_at"], reverse=True)
            if "outcome IS NULL" in sql:
                rows = [r for r in rows if r["outcome"] is None]
            return rows[: args[0]]
        return []

    async def execute(self, sql, *args):
        if "INSERT INTO strategy_calibration" in sql:
            self.calibration[args[0]] = {
                "domain": args[0], "multiplier": args[1], "offset_adj": args[2],
                "n_samples": args[3], "brier": args[4],
            }
        return "OK"


# ── Pure calibration math ───────────────────────────────────────────────────────

def test_infer_domain():
    assert cal.infer_domain("Should we build or buy a CRM?") == "tech"
    assert cal.infer_domain("Should we hire a senior engineer now?") == "hiring"
    assert cal.infer_domain("what time is it") == "general"


def test_brier_score():
    assert cal.brier_score([]) is None
    assert cal.brier_score([(1.0, 1.0), (0.0, 0.0)]) == 0.0
    assert cal.brier_score([(1.0, 0.0)]) == 1.0


def test_compute_adjustment_over_optimistic_offset_is_negative():
    # Predicted 0.8 but every decision failed (0.0) -> over-optimistic -> pull down.
    adj = cal.compute_adjustment([(0.8, "failure")] * 4)
    assert adj["n"] == 4
    assert adj["offset"] < 0
    assert adj["brier"] is not None and adj["brier"] > 0
    adjusted = cal.apply_adjustment(0.8, adj)
    assert 0.0 <= adjusted < 0.8


def test_compute_adjustment_empty_is_identity():
    adj = cal.compute_adjustment([])
    assert adj == {"multiplier": 1.0, "offset": 0.0, "n": 0, "brier": None}
    assert cal.apply_adjustment(0.6, adj) == 0.6
    assert cal.apply_adjustment(0.6, {}) == 0.6          # no adjustment -> unchanged (clamped)
    assert cal.apply_adjustment(1.5, {"offset": 0.0}) == 1.0   # always clamped to [0,1]


def test_shrinkage_dampens_sparse_data():
    one = cal.compute_adjustment([(0.9, "failure")])
    many = cal.compute_adjustment([(0.9, "failure")] * 20)
    assert abs(one["offset"]) < abs(many["offset"])      # a single outcome can't swing it hard


# ── Store flow (persist -> record -> recompute -> load) via FakeConn ──────────────

def test_store_flow_persist_record_recompute_load():
    async def _run():
        fc = FakeConn()
        opts = [sm.StrategyOption("Buy a SaaS", "r", 0.8, 0.2, 0.2, 0.5),
                sm.StrategyOption("Build in-house", "r", 0.7, 0.4, 0.6, 0.3)]
        ids = await cal.persist_predictions("Should we build or buy?", "tech", opts, conn=fc)
        assert len(ids) == 2 and all(ids)

        for pid in ids:                                  # both turned out to be failures
            res = await cal.record_outcome(pid, "failure", "didn't pan out", conn=fc)
            assert res["domain"] == "tech" and res["outcome"] == "failure"

        c = await cal.recompute_calibration("tech", conn=fc)
        assert c["n"] == 2 and c["offset"] < 0           # model was over-optimistic

        adj, n = await cal.load_calibration("tech", conn=fc)
        assert n == 2 and adj["offset"] < 0

        # A domain with no resolved decisions has no calibration.
        empty_adj, empty_n = await cal.load_calibration("finance", conn=fc)
        return empty_adj, empty_n

    empty_adj, empty_n = asyncio.run(_run())
    assert empty_n == 0 and empty_adj == {}


def test_record_outcome_unknown_id_raises_lookup():
    async def _run():
        fc = FakeConn()
        try:
            await cal.record_outcome(str(uuid.uuid4()), "success", conn=fc)
            return False
        except LookupError:
            return True
    assert asyncio.run(_run()) is True


def test_record_outcome_rejects_invalid_outcome():
    with pytest.raises(ValueError):
        asyncio.run(cal.record_outcome(str(uuid.uuid4()), "great", conn=FakeConn()))


def test_list_predictions_unresolved_filter():
    async def _run():
        fc = FakeConn()
        opts = [sm.StrategyOption("A", "r", 0.5, 0.5, 0.5, 0.5),
                sm.StrategyOption("B", "r", 0.6, 0.4, 0.3, 0.6)]
        ids = await cal.persist_predictions("q", "tech", opts, conn=fc)
        await cal.record_outcome(ids[0], "success", conn=fc)
        all_rows = await cal.list_predictions(conn=fc)
        open_rows = await cal.list_predictions(unresolved_only=True, conn=fc)
        return all_rows, open_rows
    all_rows, open_rows = asyncio.run(_run())
    assert len(all_rows) == 2 and len(open_rows) == 1
    assert open_rows[0]["outcome"] is None


# ── run_strategy applies the owner's calibration ──────────────────────────────────

_GOOD = json.dumps({
    "options": [
        {"name": "Build in-house", "rationale": "Full control", "success_probability": 0.6, "risk": 0.5, "effort": 0.8},
        {"name": "Buy a SaaS", "rationale": "Fast to ship", "success_probability": 0.7, "risk": 0.3, "effort": 0.2},
    ],
    "assumptions": ["Budget is fixed"],
    "confidence": 0.55,
    "what_would_change_it": ["A bigger budget"],
})


def _stub_llm(monkeypatch, reply):
    async def _fake(messages, **kw):
        return reply
    monkeypatch.setattr(sm, "chat_complete", _fake)


def test_run_strategy_applies_owner_calibration(monkeypatch):
    _stub_llm(monkeypatch, _GOOD)
    captured: dict = {}

    async def _no_persist(question, domain, options, *, conn=None):
        captured["domain"] = domain
        captured["raw"] = [o.success_probability for o in options]   # RAW, pre-calibration
        return ["id1", "id2"]

    async def _load(domain, *, conn=None):
        return ({"multiplier": 1.0, "offset": -0.3}, 5)              # over-optimistic history

    monkeypatch.setattr(cal, "persist_predictions", _no_persist)
    monkeypatch.setattr(cal, "load_calibration", _load)

    res = asyncio.run(run_strategy("Should we build or buy?"))
    assert res.calibrated_on == 5
    assert res.best().name == "Buy a SaaS"
    assert res.best().success_probability < 0.7        # pulled down by the -0.3 offset
    assert "calibrated on 5" in res.to_markdown()
    assert captured["domain"] == "tech"
    assert max(captured["raw"]) == 0.7                  # we persisted the RAW estimates


def test_run_strategy_without_calibration_is_unchanged(monkeypatch):
    # No DB available (default in tests) -> calibration is a no-op, calibrated_on stays 0.
    _stub_llm(monkeypatch, _GOOD)
    res = asyncio.run(run_strategy("Should we build or buy?"))
    assert res.calibrated_on == 0
    assert res.best().name == "Buy a SaaS" and res.best().success_probability == 0.7


# ── Endpoints ─────────────────────────────────────────────────────────────────

def _strategy_app() -> FastAPI:
    from api.routes.strategy import router
    from api.middleware.auth import require_auth
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[require_auth] = lambda: "admin"
    return app


def test_outcome_endpoint_records_and_recomputes(monkeypatch):
    async def _rec(pid, outcome, notes="", *, conn=None):
        return {"id": pid, "domain": "tech", "option_name": "Buy", "outcome": outcome}

    async def _recompute(domain, *, conn=None):
        return {"domain": domain, "multiplier": 1.0, "offset": -0.2, "n": 3, "brier": 0.21}

    monkeypatch.setattr(cal, "record_outcome", _rec)
    monkeypatch.setattr(cal, "recompute_calibration", _recompute)

    r = TestClient(_strategy_app()).post(
        "/api/v1/strategy/outcome",
        json={"prediction_id": "abc", "outcome": "failure", "notes": "x"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["domain"] == "tech"
    assert body["calibration"]["n"] == 3


def test_outcome_endpoint_rejects_bad_outcome():
    r = TestClient(_strategy_app()).post(
        "/api/v1/strategy/outcome", json={"prediction_id": "abc", "outcome": "nope"})
    assert r.status_code == 400


def test_outcome_endpoint_404_for_unknown(monkeypatch):
    async def _rec(pid, outcome, notes="", *, conn=None):
        raise LookupError(pid)
    monkeypatch.setattr(cal, "record_outcome", _rec)
    r = TestClient(_strategy_app()).post(
        "/api/v1/strategy/outcome", json={"prediction_id": "missing", "outcome": "success"})
    assert r.status_code == 404


def test_predictions_endpoint_lists(monkeypatch):
    async def _list(*, unresolved_only=False, limit=20, conn=None):
        assert unresolved_only is True
        return [{"id": "1", "question": "q", "option_name": "Buy", "outcome": None}]
    monkeypatch.setattr(cal, "list_predictions", _list)
    r = TestClient(_strategy_app()).get("/api/v1/strategy/predictions?unresolved=true")
    assert r.status_code == 200 and r.json()["count"] == 1
