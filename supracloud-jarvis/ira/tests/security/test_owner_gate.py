"""V1·Phase 3 — unit tests for the unified owner-gate (ira.security.owner_gate)."""
import pytest

from security.owner_gate import (
    GateDecision,
    OWNER_ONLY_DOMAINS,
    classify_domain,
    evaluate,
    is_owner_only,
)


def test_classify_domain_labels():
    assert classify_domain("run the command: docker ps") == "executor"
    assert classify_domain("open vs code for me") == "system"
    assert classify_domain("scan the network for threats") == "security"
    assert classify_domain("show me this week's leads") == "business"
    assert classify_domain("architect apply") == "architect_apply"
    assert classify_domain("what is the capital of France?") is None


def test_owner_only_union():
    # regex intent
    assert is_owner_only("run the command: docker ps") is True
    # keyword (routing.yaml restricted_keywords) — caught even without a regex match
    assert is_owner_only("show me my credentials") is True
    # general
    assert is_owner_only("what is 2 + 2") is False


def test_evaluate_blocks_nonowner():
    d = evaluate("run the command: docker ps", is_owner=False)
    assert isinstance(d, GateDecision)
    assert d.allowed is False
    assert d.required_role == "owner"
    assert d.risk_level == "restricted"
    assert d.audit_event_type == "owner_gate.block"
    assert "owner" in d.reason.lower()
    assert d.domain == "executor"


def test_evaluate_allows_owner():
    d = evaluate("run the command: docker ps", is_owner=True)
    assert d.allowed is True
    assert d.required_role == "owner"
    assert d.audit_event_type == "owner_gate.allow_owner"
    assert d.reason == ""


def test_evaluate_allows_general():
    d = evaluate("what is the capital of France?", is_owner=False)
    assert d.allowed is True
    assert d.risk_level == "public"
    assert d.required_role == "any"
    assert d.audit_event_type == "owner_gate.allow"
    assert d.domain is None


def test_decision_is_immutable():
    d = evaluate("hello", is_owner=False)
    with pytest.raises(Exception):
        d.allowed = True  # frozen dataclass


def test_owner_only_domains_exported():
    assert OWNER_ONLY_DOMAINS == frozenset(
        {"security", "business", "executor", "system", "architect_apply"}
    )
