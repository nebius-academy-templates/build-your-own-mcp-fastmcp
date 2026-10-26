"""Task 4: nothing a caller sent, no result and no credential in the export; the caller's identity."""

from support import VIEWER, attrs, dumped, find

FORBIDDEN = ("p5-secret-writer", "p5-secret-viewer", "PRIVATE_ARGUMENT_MARKER", "MISSING_PRIVATE_PATH_MARKER",
             "request 1 failed", "Authorization")


def test_t4_privacy_and_caller(start):
    server = start("http")
    server.call("search_logs", {"pattern": "PRIVATE_ARGUMENT_MARKER"})
    server.call("read_lines", {"path": "MISSING_PRIVATE_PATH_MARKER", "line": 1})
    server.rpc("tools/list", token=VIEWER)
    rows = server.stop("signal")
    assert rows, "telemetry export missing"
    for row in rows:
        text = dumped(row)
        for secret in FORBIDDEN:
            assert secret not in text, f"span leaks forbidden data {secret!r}"
    assert attrs(find(rows, "tools/call search_logs")).get("enduser.id") == "operator"
    assert attrs(find(rows, "tools/list")).get("enduser.id") == "observer"


def test_t4_resource_uris(start):
    """A URI the server refuses is caller input, whatever its shape. Only a URI the server served
    is protocol metadata."""
    server = start("stdio")
    server.rpc("resources/read", {"uri": "triage://reports/private-report-marker"})
    server.rpc("resources/read", {"uri": "triage://private-uri-marker"})
    server.rpc("resources/read", {"uri": "triage://formats"})
    served = []
    for row in server.stop("eof"):
        text = dumped(row)
        for marker in ("private-report-marker", "private-uri-marker"):
            assert marker not in text, f"span leaks the refused URI {marker!r}"
        if row.span.name == "resources/read" and "mcp.resource.uri" in attrs(row):
            served.append(attrs(row)["mcp.resource.uri"])
    assert served == ["triage://formats"], f"only the served resource's URI belongs on a resources/read span: {served}"
