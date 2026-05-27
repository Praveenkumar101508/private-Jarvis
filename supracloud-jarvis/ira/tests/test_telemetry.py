"""Unit tests for utils/telemetry.py — OpenTelemetry setup."""
import os
import pytest
from unittest.mock import patch


def test_setup_telemetry_no_endpoint_returns_none():
    with patch.dict(os.environ, {"OTLP_ENDPOINT": ""}):
        from utils import telemetry as t
        t._tracer = None  # reset global
        result = t.setup_telemetry("test-service")
        assert result is None  # no endpoint → returns early


def test_get_tracer_returns_noop_when_disabled():
    from utils import telemetry as t
    t._tracer = None
    tracer = t.get_tracer()
    assert tracer is not None


def test_trace_span_context_manager():
    from utils.telemetry import trace_span
    with trace_span("test.operation", {"key": "value"}):
        pass  # should not raise


def test_trace_span_propagates_exception():
    from utils.telemetry import trace_span
    with pytest.raises(ValueError):
        with trace_span("test.error"):
            raise ValueError("deliberate test error")
