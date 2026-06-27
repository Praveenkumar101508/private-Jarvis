"""Tests for the human-feel affective layer (agents/affect.py).

All pure-Python — no LLM/GPU/DB. Covers state update/decay/persistence, coarse
situation inference, the supportive-not-amplifying guardrails, and the AffectLayer
preamble (persona + mood + relational memory, fail-soft).
"""
from __future__ import annotations

import pytest

from agents.affect import (
    AffectLayer,
    AffectState,
    Persona,
    _arousal_baseline,
    affect_enabled,
    infer_situation,
    interaction_signal,
    style_guidance,
)


# ── AffectState: update, clamp, decay, persist, mood, voice ──────────────────

def test_state_update_clamps():
    s = AffectState(valence=0.9, arousal=0.9)
    s.update(0.5, 0.5)
    assert s.valence == 1.0 and s.arousal == 1.0
    s.update(-5.0, -5.0)
    assert s.valence == -1.0 and s.arousal == 0.0


def test_state_decays_toward_baseline():
    now = 1_000_000.0
    s = AffectState(valence=0.8, arousal=0.95, updated=now)
    s.decay(now + 10_000)   # many half-lives later
    assert abs(s.valence) < 0.05
    assert abs(s.arousal - _arousal_baseline(now + 10_000)) < 0.05


def test_state_roundtrip():
    s = AffectState(valence=-0.4, arousal=0.7, updated=123.0)
    s2 = AffectState.from_dict(s.to_dict())
    assert (round(s2.valence, 3), round(s2.arousal, 3)) == (-0.4, 0.7)


def test_mood_labels():
    assert AffectState(valence=0.6, arousal=0.7).mood_label() == "upbeat"
    assert AffectState(valence=0.6, arousal=0.2).mood_label() == "content"
    assert AffectState(valence=-0.6, arousal=0.7).mood_label() == "tense"
    assert AffectState(valence=-0.6, arousal=0.2).mood_label() == "low"
    assert AffectState(valence=0.0, arousal=0.2).mood_label() == "neutral"


def test_voice_style_maps_mood():
    low = AffectState(valence=-0.6, arousal=0.2).voice_style()
    assert "gentle" in low["instruct"] and low["speed"] < 1.0
    upbeat = AffectState(valence=0.6, arousal=0.7).voice_style()
    assert upbeat["speed"] > 1.0


# ── Signals + situation inference ────────────────────────────────────────────

def test_interaction_signal_direction():
    dv_pos, _ = interaction_signal("thanks, this is great")
    dv_neg, _ = interaction_signal("no this is broken and wrong")
    assert dv_pos > 0 > dv_neg


def test_infer_situation_labels():
    assert infer_situation("") == "neutral"
    assert infer_situation("I'm so tired and exhausted today") == "low"
    assert infer_situation("I'm completely stuck and overwhelmed") == "stressed"
    assert infer_situation("need this asap") == "busy"
    assert infer_situation("heads down building the parser") == "focused"
    assert infer_situation("just relaxing this weekend") == "relaxed"


def test_infer_situation_cadence_busy():
    assert infer_situation("status?", cadence=2.0) == "busy"


# ── Guardrails (coarse, supportive, never overrides correctness) ─────────────

def test_low_guidance_is_supportive_not_amplifying():
    g = style_guidance(AffectState(valence=-0.6, arousal=0.2), "low").lower()
    assert "do not mirror or amplify" in g
    assert "diagnostic" in g                    # no clinical claims guardrail
    assert "never changes facts" in g           # affect can't override correctness


def test_busy_guidance_is_terse():
    g = style_guidance(AffectState(), "busy").lower()
    assert "terse" in g


# ── AffectLayer: observe, preamble, recall, persistence ──────────────────────

async def test_preamble_includes_persona_state_and_memory():
    async def recall(q):
        return ["last time this came up you were heads-down on the deadline"]

    layer = AffectLayer(persona=Persona(owner="Praveen"), recall=recall)
    layer.observe("I'm so tired today")
    pre = await layer.preamble("how's the project")
    assert "Praveen" in pre
    assert "mood=" in pre
    assert "deadline" in pre        # relational memory pulled into the preamble


async def test_preamble_failsoft_when_recall_raises():
    async def boom(q):
        raise RuntimeError("db down")

    layer = AffectLayer(recall=boom)
    pre = await layer.preamble("anything")
    assert "IRA" in pre             # persona still present; no crash, no memory block


async def test_preamble_without_recall():
    pre = await AffectLayer().preamble("x")
    assert "Inner state" in pre


def test_observe_moves_valence_down_on_negative():
    layer = AffectLayer()
    base = layer.state.valence
    layer.observe("this is broken and frustrating and wrong")
    assert layer.state.valence < base
    assert layer.situation in ("stressed", "low")


def test_save_and_load_roundtrip(tmp_path):
    path = str(tmp_path / "affect.json")
    a = AffectLayer(path=path)
    a.observe("thanks, awesome work")
    a.state.valence = 0.42
    assert a.save() is True
    b = AffectLayer(path=path)
    assert b.load() is True
    assert round(b.state.valence, 2) == 0.42


def test_save_noop_without_path():
    assert AffectLayer(path="").save() is False


# ── Flag ──────────────────────────────────────────────────────────────────────

def test_affect_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IRA_BRAIN_AFFECT_ENABLED", raising=False)
    assert affect_enabled() is False


def test_affect_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("IRA_BRAIN_AFFECT_ENABLED", "true")
    assert affect_enabled() is True
