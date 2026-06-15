"""Phase 0 smoke test — proves the pytest harness and CI wiring work end to end.
Intentionally trivial; real tests arrive with the bridge (Phase 2)."""


def test_smoke():
    assert 1 + 1 == 2
