"""Task 2: the caller's trace context from _meta, on both transports."""

import pytest

from support import SERVER_KIND, find, structured

PARENT_TRACE = "4bf92f3577b34da6a3ce929d0e0e4736"
PARENT_SPAN = "00f067aa0ba902b7"


def test_t2_optional_params(start):
    """Legacy MCP permits requests with no params. The server must keep answering them while it
    reads optional metadata."""
    server = start("stdio")
    server.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-11-25", "clientInfo": {"name": "telemetry-checks", "version": "1"},
                            "capabilities": {}}})
    init = server.reply("initialize")
    assert "error" not in init, f"legacy initialization failed: {init}"
    server.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    server.send({"jsonrpc": "2.0", "id": 2, "method": "ping"})
    result = server.reply("ping")
    assert "result" in result and "error" not in result, f"parameter-free ping must succeed: {result}"
    rows = server.stop("eof")
    assert find(rows, "ping").span.kind == SERVER_KIND
    assert not any(row.span.name == "notifications/initialized" for row in rows), (
        "notification must not create a span")


@pytest.mark.parametrize("transport", ["stdio", "http"])
def test_t2_parent(start, transport):
    server = start(transport)
    server.call("list_logs", {}, {"traceparent": f"00-{PARENT_TRACE}-{PARENT_SPAN}-01", "tracestate": "vendor=value"})
    row = find(server.stop("signal"), "tools/call list_logs")
    assert row.span.trace_id.hex() == PARENT_TRACE, (
        f"the span must join the trace in _meta traceparent: trace {row.span.trace_id.hex()}")
    assert row.span.parent_span_id.hex() == PARENT_SPAN, (
        f"the caller's span in _meta traceparent must be the parent: {row.span.parent_span_id.hex() or 'none'}")
    assert row.span.trace_state == "vendor=value", f"_meta tracestate must be kept: {row.span.trace_state!r}"


def test_t2_unsampled(start):
    server = start("stdio")
    server.call("list_logs", {}, {"traceparent": f"00-{PARENT_TRACE}-{PARENT_SPAN}-00"})
    server.call("list_logs", {})
    own = 0
    for row in server.stop("eof"):
        assert row.span.trace_id.hex() != PARENT_TRACE, "unsampled parent must not export its descendants"
        if row.span.name == "tools/call list_logs":
            own += 1
    # The second call has no caller context, so it starts its own sampled trace.
    assert own == 1, f"the call without caller context must export its own span: {own} exported"


def test_t2_scan_is_not_trace(start):
    server = start("stdio")
    scan = structured(server.call("summarize_logs", {"min_level": "any"}))
    arguments = {"scan_id": scan["scan_id"], "group_id": scan["groups"][0]["group_id"]}
    server.call("group_lines", arguments)
    server.call("group_lines", arguments)
    calls = [row for row in server.stop("eof") if row.span.kind == SERVER_KIND]
    assert len(calls) == 3, f"each of the three calls must export its own SERVER span: {len(calls)} exported"
    assert len({row.span.trace_id for row in calls}) == 3, "a reused scan_id must not reuse another request's trace"
