"""V2·Phase 4 — docker-compose.portable.yml shape: self-contained, relative volumes,
loopback-only port publishing, demo banner wired."""
from pathlib import Path

import pytest
import yaml

_COMPOSE = Path(__file__).resolve().parents[3] / "docker-compose.portable.yml"


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(_COMPOSE.read_text())


def test_compose_parses_and_has_core_services(compose):
    services = compose["services"]
    for name in ("postgres", "redis", "ollama", "ira-api", "frontend"):
        assert name in services, f"missing service {name}"


def test_volumes_are_relative_to_the_bundle(compose):
    for svc in compose["services"].values():
        for vol in svc.get("volumes", []):
            host = vol.split(":")[0] if isinstance(vol, str) else vol.get("source", "")
            # named volumes are not used; every bind starts ./ so it stays on the stick
            assert host.startswith("./"), f"non-relative volume: {vol}"


def test_ports_published_to_loopback_only(compose):
    for name in ("ira-api", "frontend"):
        for port in compose["services"][name].get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} not loopback-bound: {port}"


def test_api_pinned_to_local_engine(compose):
    env = compose["services"]["ira-api"]["environment"]
    assert env["IRA_MODE"] == "portable_demo"
    assert env["IRA_USE_CORTEX"] == "false"
    assert env["WEB_SEARCH_ENABLED"] == "false"
    assert env["LLM_BACKEND"] == "ollama"


def test_demo_banner_enabled(compose):
    assert compose["services"]["frontend"]["environment"]["NEXT_PUBLIC_IRA_DEMO_MODE"] == "true"
