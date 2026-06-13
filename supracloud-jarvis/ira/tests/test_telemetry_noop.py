"""v1 fix — telemetry degrades to a no-op when opentelemetry is absent or disabled.

get_tracer()/trace_span() must never raise ModuleNotFoundError just because otel
isn't installed. These tests force both conditions and assert trace_span is a safe
no-op that still lets real exceptions propagate.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import sys

import pytest

import utils.telemetry as tel


def test_trace_span_noop_when_opentelemetry_absent(monkeypatch):
    # Disabled tracer + make `from opentelemetry import trace` fail inside get_tracer().
    monkeypatch.setattr(tel, "_tracer", None)
    monkeypatch.setitem(sys.modules, "opentelemetry", None)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", None)

    # Degrades to the no-op tracer rather than raising ModuleNotFoundError.
    assert tel.get_tracer() is tel._NOOP_TRACER

    # trace_span is a working no-op context manager — raises nothing.
    with tel.trace_span("unit", {"k": "v"}) as span:
        assert span is not None
        assert span.is_recording() is False

    # A real exception inside the span still propagates (telemetry never masks it).
    with pytest.raises(ValueError):
        with tel.trace_span("boom"):
            raise ValueError("x")


def test_trace_span_safe_when_otel_present_but_disabled():
    # otel IS installed in CI but no provider configured -> non-recording, no crash.
    with tel.trace_span("ok", {"a": 1}) as span:
        assert span is not None
