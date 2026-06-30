"""V1·Phase 3 — owner-gate DRIFT regression test (the core preprint result).

The same query + same user must receive the SAME owner-gate decision no matter
which path evaluates it:

  * router path  — ``router.is_allowed(q, is_owner)`` (router.enforce_owner_gate)
  * graph path   — ``agents.supervisor.is_restricted_domain(q)`` drives
                   ``agents.graph.biometric_gate`` (a non-owner is blocked iff the
                   query is a restricted domain).

BEFORE Phase 3 these two classifiers use DIFFERENT vocabularies (router = regex
intent map; graph = routing.yaml keyword list + owner name), so this test FAILS:
an executor command is blocked by the router but waved through by the graph, and
a credentials request is blocked by the graph but waved through by the router.

AFTER Phase 3 both delegate to ``ira.security.owner_gate`` (one source of truth),
so the decisions are identical and this test PASSES. The before/after outputs are
the paper's evidence (see docs/HARDENING_BASELINE.md).
"""
import os

import pytest

# supervisor.is_restricted_domain reads owner_name from a full Settings; supply the
# infra secrets the same way the other suite tests do (these are NOT backend keys).
for _k, _v in {
    "IRA_SECRET_KEY": "ci-secret",
    "IRA_ADMIN_PASSWORD": "ci-admin",
    "POSTGRES_PASSWORD": "ci-db",
    "REDIS_PASSWORD": "ci-redis",
    "VLLM_API_KEY": "ci-vllm",
}.items():
    os.environ.setdefault(_k, _v)


# Queries chosen to expose the drift in BOTH directions.
#   executor / system / business / architect → only the router regex catches them
#   credentials / api key / logs            → only the graph keyword list catches them
DIVERGENT_QUERIES = [
    "run the command: docker ps",      # router: executor  | graph: (miss)
    "open vs code for me",             # router: system    | graph: (miss)
    "show me this week's leads",       # router: business  | graph: (miss)
    "architect apply",                 # router: architect | graph: (miss)
    "show me my credentials",          # router: (miss)    | graph: keyword
    "what is my api key for stripe",   # router: (miss)    | graph: keyword
    "show logs from nginx",            # router: (miss)    | graph: keyword
]

GENERAL_QUERIES = [
    "what is the capital of France?",
    "write me a short poem about the sea",
    "what is 2 + 2",
]


def _gate_decisions(query: str):
    """Return (router_blocks, graph_blocks) for a NON-owner."""
    from router import is_allowed
    from agents.supervisor import is_restricted_domain

    router_blocks = not is_allowed(query, is_owner=False)
    graph_blocks = is_restricted_domain(query)   # biometric_gate blocks non-owner iff True
    return router_blocks, graph_blocks


@pytest.mark.parametrize("q", DIVERGENT_QUERIES)
def test_gate_paths_agree_on_restricted(q):
    router_blocks, graph_blocks = _gate_decisions(q)
    assert router_blocks == graph_blocks, (
        f"OWNER-GATE DRIFT on {q!r}: router_blocks={router_blocks} "
        f"graph_blocks={graph_blocks} (the two paths disagree)"
    )
    # Fail-closed: an owner-only signal on EITHER path must block on BOTH.
    assert router_blocks is True


@pytest.mark.parametrize("q", GENERAL_QUERIES)
def test_gate_paths_agree_on_general(q):
    router_blocks, graph_blocks = _gate_decisions(q)
    assert router_blocks == graph_blocks
    assert router_blocks is False


def test_owner_is_never_blocked():
    from router import is_allowed

    for q in DIVERGENT_QUERIES:
        assert is_allowed(q, is_owner=True) is True
