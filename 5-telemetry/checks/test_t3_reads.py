"""Task 3: per-file read spans with exact work counters."""

from support import INTERNAL_KIND, PLAIN, attrs, find, integer, structured

# 400 short app-log lines, about 20 KB: more than a format detection needs, less than one 64 KiB read
LONG = "".join(f"2040-01-01T00:{i // 60:02d}:{i % 60:02d}.000Z INFO worker step {i} done\n" for i in range(400))


def records(data: bytes) -> int:
    """Newline records in data, counting a final nonempty unterminated one."""
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)


def test_t3_reading(start):
    server = start("stdio")
    scan = structured(server.call("summarize_logs", {"min_level": "any"}))
    groups = scan.get("groups")
    assert groups, "synthetic app logs must produce groups"
    server.call("group_lines", {"scan_id": scan["scan_id"], "group_id": groups[0]["group_id"]})
    rows = server.stop("eof")
    summary = find(rows, "tools/call summarize_logs")
    group_call = find(rows, "tools/call group_lines")
    files = lines = read_bytes = reused_bytes = reads = 0
    for row in rows:
        parent = row.span.parent_span_id
        if parent == summary.span.span_id:
            if row.span.name == "logtriage.read":
                reads += 1
                assert row.span.kind == INTERNAL_KIND
                files += integer(attrs(row).get("logtriage.files"))
                lines += integer(attrs(row).get("logtriage.lines"))
                read_bytes += integer(attrs(row).get("logtriage.bytes"))
            assert row.span.trace_id == summary.span.trace_id, "inner span must be in the request trace"
        if parent == group_call.span.span_id and row.span.name == "logtriage.read":
            reused_bytes += integer(attrs(row).get("logtriage.bytes"))
    assert reads == 4, f"summarize_logs over two files needs 4 logtriage.read children (detection and content): {reads}"
    assert files == 4, f"logtriage.files summed over the read spans: {files}, want 4"
    assert lines == 8, f"logtriage.lines summed over the read spans: {lines}, want 8"
    assert read_bytes == 4 * len(PLAIN), f"logtriage.bytes summed over the read spans: {read_bytes}, want {4 * len(PLAIN)}"
    assert 0 < reused_bytes < read_bytes, (
        f"stored group read bytes={reused_bytes} must be positive and below full scan={read_bytes}")


def test_t3_no_read_for_refused_path(start):
    server = start("stdio")
    server.call("read_lines", {"path": "../forbidden", "line": 1})
    rows = server.stop("eof")
    find(rows, "tools/call read_lines")
    assert not any(row.span.name == "logtriage.read" for row in rows), "no read span when no file was opened"


def test_t3_lines_count_what_was_read(start):
    """logtriage.lines counts the records in the bytes a reader returned, read-ahead included, not
    the lines the parser took from them. list_logs detects the format, which opens a reader."""
    server = start("stdio")
    (server.root / "long").mkdir()
    (server.root / "long" / "gamma.log").write_text(LONG, encoding="utf-8")
    server.call("list_logs", {"path": "long"})
    rows = server.stop("eof")
    content = LONG.encode("utf-8")
    reads = [row for row in rows if row.span.name == "logtriage.read"]
    assert reads, "list_logs detects the file's format, which opens a reader: no logtriage.read span"
    for row in reads:
        read = integer(attrs(row).get("logtriage.bytes"))
        lines = integer(attrs(row).get("logtriage.lines"))
        want = records(content[:read])
        assert lines == want, f"logtriage.lines must count the records in the {read} bytes read: {lines}, want {want}"
