"""
OpenTelemetry setup for IRA.
Sends traces to any OTLP endpoint (Grafana Cloud, Honeycomb, Jaeger, etc.)

Set OTLP_ENDPOINT in .env to enable. Leave blank to disable silently.
Example (Grafana Cloud):
  OTLP_ENDPOINT=https://otlp-gateway-prod-eu-west-0.grafana.net/otlp
  OTLP_HEADERS=Authorization=Basic <base64(instanceId:apiKey)>
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("ira.telemetry")

_tracer = None


def setup_telemetry(service_name: str = "ira-api") -> None:
    """Initialise OpenTelemetry SDK. Call once from main.py lifespan."""
    global _tracer

    endpoint = os.getenv("OTLP_ENDPOINT", "").strip()
    if not endpoint:
        logger.info("Telemetry: OTLP_ENDPOINT not set — tracing disabled")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv("GIT_SHA", "unknown"),
        })

        headers_raw = os.getenv("OTLP_HEADERS", "")
        headers = {}
        for pair in headers_raw.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                headers[k.strip()] = v.strip()

        exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        _tracer = trace.get_tracer(service_name)
        logger.info(f"Telemetry: OTLP tracing enabled → {endpoint}")

    except Exception as e:
        logger.warning(f"Telemetry setup failed (non-fatal): {e}")


def get_tracer():
    """Get the tracer. Returns a no-op tracer if telemetry is disabled OR if
    opentelemetry isn't installed — so otel stays a fully optional dependency."""
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace
        return trace.get_tracer("ira-noop")
    except Exception:
        return _NOOP_TRACER


# ── No-op fallbacks (opentelemetry absent / telemetry disabled) ───────────────
# So trace_span() never raises ModuleNotFoundError when otel isn't installed.
class _NoopSpan:
    def is_recording(self) -> bool:
        return False

    def set_attribute(self, *args, **kwargs) -> None:
        pass

    def record_exception(self, *args, **kwargs) -> None:
        pass

    def set_status(self, *args, **kwargs) -> None:
        pass


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, name: str, *args, **kwargs):
        yield _NoopSpan()


_NOOP_TRACER = _NoopTracer()


@contextmanager
def trace_span(name: str, attributes: dict[str, Any] | None = None):
    """Context manager for a named span. No-op if telemetry is disabled."""
    tracer = get_tracer()
    with tracer.start_as_current_span(name) as span:
        if attributes and span.is_recording():
            for k, v in attributes.items():
                span.set_attribute(k, str(v))
        try:
            yield span
        except Exception as e:
            if span.is_recording():
                from opentelemetry.trace import StatusCode
                span.record_exception(e)
                span.set_status(StatusCode.ERROR, str(e))
            raise
