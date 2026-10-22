"""Task 1: export is opt-in, carries the service name and version, and is flushed before exit."""

import pytest

from support import find


def test_t1_disabled(start):
    server = start("stdio", enabled=False)
    server.call("list_logs", {})
    rows = server.stop("eof")
    assert not rows, f"telemetry must be off without an endpoint: {len(rows)} spans"


@pytest.mark.parametrize("transport, how", [("stdio", "eof"), ("stdio", "signal"), ("http", "signal")],
                         ids=["stdio-eof", "stdio-signal", "http-signal"])
def test_t1_export_and_shutdown(start, transport, how):
    server = start(transport, extra={"OTEL_SERVICE_NAME": "p5-test-service"})
    server.call("list_logs", {})
    row = find(server.stop(how), "tools/call list_logs")
    assert row.resource.get("service.name") == "p5-test-service", (
        f"resource service.name must come from OTEL_SERVICE_NAME: {row.resource.get('service.name')!r}")
    assert row.resource.get("service.version") == "0.5.0", (
        f"resource service.version must be the server version 0.5.0: {row.resource.get('service.version')!r}")
