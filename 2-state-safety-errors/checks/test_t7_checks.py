"""Task 7: checks behind the schema (E3, E4, E5, E9, evidence), closed evidence items, masking."""

from __future__ import annotations

import pytest

from support import (
    CALLS, E4, branches, e1, e2, e3, e5, e8, e9, e10, masked, ok, refused_by_schema, resolve,
    tool_error,
)

APP = "pods/provisioner-2/archive/app-2026-08-30.log.gz"
PHP = "vms/web-01/archive/php-fpm-2026-08-30.log.gz"
PHP_LINES = CALLS["read-php-dot-slash"]["result"]["total_lines"]
GOOD_ITEM = {"file": PHP, "line": 2, "note": "the pool starts"}


def finding(title: str, *evidence: dict) -> dict:
    return {"title": title, "severity": "medium", "summary": "Checked twice.",
            "evidence": list(evidence) or [GOOD_ITEM]}


def written(server) -> list[str]:
    return sorted(p.name for p in server.reports.iterdir()) if server.reports.exists() else []


def test_save_finding_metadata_matches_create_only_behavior(server):
    tool = server.tool("save_finding")
    hints = tool.get("annotations") or {}
    assert hints.get("destructiveHint") is False, (
        "save_finding: destructiveHint must be false because an existing report is left unchanged"
    )


@pytest.mark.parametrize("tool, args, field", [
    ("summarize_logs", {"path": APP, "since": "yesterday"}, "since"),
    ("summarize_logs", {"path": APP, "until": "2026-13-01"}, "until"),
    ("search_logs", {"path": APP, "pattern": "quota", "since": "noon"}, "since"),
    ("search_logs", {"path": APP, "pattern": "quota", "until": "2026-08-30 10:00"}, "until"),
    ("search_logs", {"path": APP, "pattern": "quota", "until": "2026-08-30T24:00"}, "until"),
], ids=["summarize-since-word", "summarize-until-month-13", "search-since-word", "search-until-space", "search-until-hour-24"])
def test_a_window_end_that_does_not_read(server, tool, args, field):
    server.tool(tool)
    tool_error(server.call(tool, args), e3(field), server.root)


@pytest.mark.parametrize("tool, args", [
    ("summarize_logs", {"path": APP, "since": "2026-08-30T10:00", "until": "2026-08-30T10:00:00Z"}),
    ("summarize_logs", {"path": APP, "since": "2026-08-31", "until": "2026-08-30"}),
    ("search_logs", {"path": APP, "pattern": "quota", "since": "2026-08-30T12:00+02:00",
                     "until": "2026-08-30T10:00Z"}),
], ids=["summarize-equal", "summarize-reversed", "search-equal-after-zones"])
def test_until_before_since(server, tool, args):
    server.tool(tool)
    tool_error(server.call(tool, args), E4, server.root)


@pytest.mark.parametrize("pattern", ["quota(", "[unclosed", "*quota"])
def test_a_pattern_that_does_not_compile(server, pattern):
    server.tool("search_logs")
    tool_error(server.call("search_logs", {"path": APP, "pattern": pattern}), e5("pattern"), server.root)


def test_an_existing_finding_is_not_overwritten(server):
    server.tool("save_finding")
    ok(server.call("save_finding", finding("Nightly sync ran late")))
    before = (server.reports / "nightly-sync-ran-late.md").read_bytes()
    reply = server.call("save_finding", {**finding("Nightly sync ran late!"), "severity": "critical"})
    tool_error(reply, e9("nightly-sync-ran-late"), server.root)
    assert (server.reports / "nightly-sync-ran-late.md").read_bytes() == before, (
        "a refused save_finding must leave the existing file as it was"
    )


@pytest.mark.parametrize("item, text", [
    ({"file": "../outside.log", "line": 1, "note": "x"}, e1("../outside.log")),
    ({"file": "/etc/hosts", "line": 1, "note": "x"}, e1("/etc/hosts")),
    ({"file": "vms/web-01/archive/no-such-file.log.gz", "line": 1, "note": "x"},
     e2("vms/web-01/archive/no-such-file.log.gz")),
    ({"file": "vms/web-01", "line": 1, "note": "x"}, e10("vms/web-01")),
    ({"file": ".", "line": 1, "note": "x"}, e10(".")),
    ({"file": PHP, "line": PHP_LINES + 1, "note": "x"}, e8(PHP_LINES + 1, PHP, PHP_LINES)),
    ({"file": "./" + PHP, "line": 99, "note": "x"}, e8(99, PHP, PHP_LINES)),
], ids=["outside", "absolute-outside", "missing", "folder", "root", "past-the-end", "past-the-end-dot-slash"])
def test_evidence_is_checked_and_nothing_is_written(server, item, text):
    server.tool("save_finding")
    before = written(server)
    reply = server.call("save_finding", finding("Evidence under review", GOOD_ITEM, item))
    tool_error(reply, text, server.root)
    assert written(server) == before, "a refused save_finding must write nothing"


def test_an_existing_name_is_refused_before_the_evidence(server):
    server.tool("save_finding")
    ok(server.call("save_finding", finding("Backup window overlaps")))
    bad = {"file": "vms/web-01", "line": 1, "note": "x"}
    reply = server.call("save_finding", finding("Backup window overlaps", bad))
    tool_error(reply, e9("backup-window-overlaps"), server.root)


def test_evidence_items_are_checked_in_order(server):
    server.tool("save_finding")
    first = {"file": "nope.log", "line": 1, "note": "x"}
    second = {"file": "vms/web-01", "line": 1, "note": "x"}
    reply = server.call("save_finding", finding("Two bad items", GOOD_ITEM, first, second))
    tool_error(reply, e2("nope.log"), server.root)


def test_evidence_items_are_closed(server):
    tool = server.tool("save_finding")
    root = tool["inputSchema"]
    items = [b.get("items") for b in branches(root["properties"]["evidence"], root) if b.get("items")]
    assert items, "save_finding.evidence: the schema must describe its items"
    item = resolve(items[0], root)
    assert item.get("additionalProperties") is False, (
        "save_finding.evidence items must refuse keys other than file, line and note "
        f"(additionalProperties: false), got {item.get('additionalProperties')!r}"
    )
    before = written(server)
    reply = server.call("save_finding", finding("Closed items", {**GOOD_ITEM, "severity": "high"}))
    refused_by_schema(reply, "an evidence item has only file, line and note")
    assert written(server) == before, "a refused save_finding must write nothing"


def test_a_good_finding_is_still_saved(server):
    server.tool("save_finding")
    item = {"file": "./" + PHP, "line": PHP_LINES, "note": "the last line"}
    result = ok(server.call("save_finding", finding("Pool stops cleanly", item)))
    assert result.get("name") == "pool-stops-cleanly", f"save_finding: name {result.get('name')!r}"
    assert (server.reports / "pool-stops-cleanly.md").is_file(), "a finding whose evidence checks out is written"


def test_unexpected_errors_are_masked(hostile_server, hostile):
    hostile_server.tool("read_lines", "Task 4 registers read_lines.")
    reply = hostile_server.call("read_lines", {"path": "broken/bad.log.gz", "line": 1})
    masked(reply, hostile.root)
