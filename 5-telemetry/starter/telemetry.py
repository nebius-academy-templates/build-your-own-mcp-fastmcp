"""Opt-in trace export: a tracer provider with a batching OTLP/HTTP exporter, or nothing at all.

Export starts only when an OTLP endpoint variable is set. The exporter reads the endpoint and its
headers from the standard OTEL_ variables itself, so no endpoint, header or key passes through
this module or reaches a log line.

Provided for task 1 of practice 5. Copy it to solution/src/logtriage/telemetry.py, call configure
before the server is created, and flush on every way out with shutdown or flush_and_exit
(5-telemetry/README.md).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import TYPE_CHECKING

from opentelemetry import trace

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

ENDPOINT_VARIABLES = ("OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
SERVICE_NAME = "log-triage"
FLUSH_SECONDS = 5.0

_provider: TracerProvider | None = None


def enabled() -> bool:
    """Whether spans leave the process."""
    return _provider is not None


class _ExportFailure(logging.Handler):
    """One fixed stderr line per SDK warning: the SDK's own messages can name the endpoint."""

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno >= logging.WARNING:
            sys.stderr.write("telemetry: export failed\n")


def configure(version: str) -> bool:
    """Install the provider and its exporter when an endpoint is set. False, and nothing installed,
    without one."""
    if not any(os.environ.get(name) for name in ENDPOINT_VARIABLES):
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    sdk_log = logging.getLogger("opentelemetry")
    sdk_log.handlers[:] = [_ExportFailure()]
    sdk_log.propagate = False
    install(provider_for(version, OTLPSpanExporter()))
    return True


def provider_for(version: str, exporter: SpanExporter) -> TracerProvider:
    """A provider that batches ended spans for exporter, named by OTEL_SERVICE_NAME or log-triage."""
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    name = os.environ.get("OTEL_SERVICE_NAME") or SERVICE_NAME
    resource = Resource.create({"service.name": name, "service.version": version})
    provider = TracerProvider(resource=resource, shutdown_on_exit=False)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    return provider


def install(provider: TracerProvider) -> None:
    """Send every span to provider. The server's own tests install one with an in-memory exporter."""
    global _provider
    trace.set_tracer_provider(provider)
    _provider = provider


def shutdown(provider: TracerProvider | None = None) -> bool:
    """Export the ended spans still waiting in the batch and stop the exporter, within FLUSH_SECONDS.
    False when the bound ran out first.

    The SDK's own shutdown waits up to 30 seconds on a backend that doesn't answer, so it runs in a
    daemon thread that the process doesn't wait for past the bound.
    """
    provider = provider or _provider
    if provider is None:
        return True
    worker = threading.Thread(target=provider.shutdown, daemon=True)
    worker.start()
    worker.join(FLUSH_SECONDS)
    return not worker.is_alive()


def flush_and_exit(*_: object) -> None:
    """A signal over stdio: flush, then end the process at once. A normal exit would wait on the
    thread that is blocked reading stdin."""
    shutdown()
    os._exit(0)
