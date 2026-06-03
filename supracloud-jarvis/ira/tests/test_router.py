"""Router-level owner-gate enforcement (Phase 4, part 3) — pure IRA logic, no gateway."""
import pytest

from router import enforce_owner_gate, is_allowed, restricted_domain

RESTRICTED_QUERIES = [
    ("lock down the system now", "security"),
    ("scan the network for threats", "security"),
    ("text my phone the secure code", "security"),
    ("show me this week's leads and bookings", "business"),
    ("run the command: docker ps", "executor"),
    ("open vs code for me", "system"),
    ("architect apply", "architect_apply"),
    ("architect implement: calendar sync", "architect_apply"),
]

GENERAL_QUERIES = [
    "teach me how a hash map works",
    "what is the capital of France?",
    "write me a short poem about the sea",
    "explain the CAP theorem",
]


@pytest.mark.parametrize("q,domain", RESTRICTED_QUERIES)
def test_restricted_domain_detected(q, domain):
    assert restricted_domain(q) == domain


@pytest.mark.parametrize("q,_", RESTRICTED_QUERIES)
def test_nonowner_blocked_on_restricted(q, _):
    refusal = enforce_owner_gate(q, is_owner=False)
    assert refusal is not None and "owner" in refusal.lower()
    assert is_allowed(q, is_owner=False) is False


@pytest.mark.parametrize("q,_", RESTRICTED_QUERIES)
def test_owner_allowed_on_restricted(q, _):
    assert enforce_owner_gate(q, is_owner=True) is None
    assert is_allowed(q, is_owner=True) is True


@pytest.mark.parametrize("q", GENERAL_QUERIES)
def test_general_open_to_nonowner(q):
    assert restricted_domain(q) is None
    assert is_allowed(q, is_owner=False) is True
