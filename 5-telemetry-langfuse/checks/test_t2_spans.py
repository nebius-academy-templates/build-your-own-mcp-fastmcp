"""Task 2: one SERVER span per request, named and classified by the MCP conventions."""

from support import SERVER_KIND, STATUS_ERROR, attrs, find


def test_t2_requests_and_errors(start):
    server = start("stdio")
    server.rpc("tools/list")
    server.call("list_logs", {"path": "../forbidden"})
    server.rpc("prompts/get", {"name": "triage", "arguments": {}})
    server.rpc("resources/read", {"uri": "triage://reports"})
    rows = server.stop("eof")
    for name in ("tools/list", "tools/call list_logs", "prompts/get triage", "resources/read"):
        row = find(rows, name)
        assert row.span.kind == SERVER_KIND, f"{name} must be a SERVER span"
        assert attrs(row).get("mcp.method.name") == name.split(" ")[0], (
            f"{name}: mcp.method.name is {attrs(row).get('mcp.method.name')!r}")
        count = sum(1 for other in rows if other.span.name == name)
        assert count == 1, f"{name}: {count} spans, want 1"
    row = find(rows, "tools/call list_logs")
    assert attrs(row).get("error.type") == "tool_error", (
        f"a refused tool call needs error.type tool_error: {attrs(row).get('error.type')!r}")
    assert row.span.status.code == STATUS_ERROR, "a refused tool call needs status ERROR"
    assert attrs(row).get("gen_ai.operation.name") == "execute_tool", (
        f"a tools/call span needs gen_ai.operation.name execute_tool: {attrs(row).get('gen_ai.operation.name')!r}")
    assert attrs(row).get("gen_ai.tool.name") == "list_logs", (
        f"a tools/call span needs gen_ai.tool.name: {attrs(row).get('gen_ai.tool.name')!r}")
    assert "trace_id=" + row.span.trace_id.hex() in server.stderr_text(), (
        "debug tool log must contain its server span's trace_id")
    prompt = find(rows, "prompts/get triage")
    assert attrs(prompt).get("gen_ai.prompt.name") == "triage", (
        f"a prompts/get span needs gen_ai.prompt.name: {attrs(prompt).get('gen_ai.prompt.name')!r}")
    assert prompt.span.status.code != STATUS_ERROR, "invalid prompt arguments are not a server failure"
    uri = attrs(find(rows, "resources/read")).get("mcp.resource.uri")
    assert uri == "triage://reports", f"a served resource's resources/read span needs mcp.resource.uri: {uri!r}"
