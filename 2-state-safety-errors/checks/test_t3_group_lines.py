"""Task 3: group_lines: a group's lines from a scan, paging, the cap, E6 and E7."""

from __future__ import annotations

import time

import pytest

from support import (
    CALLS, S3_LOGS, SCAN_ID_RE, Server, calls_for, check_answer, check_description, check_error,
    check_plain, check_read_annotations, check_title, e6, make_entry, ok, output_fields,
    refused_by_schema, required_of, tool_error,
)

TASK = "Task 3 registers group_lines."
APP = "pods/provisioner-2/archive/app-2026-08-30.log.gz"
TOP = CALLS["group-app-any-first"]["group_id"]


def test_group_lines_title_and_annotations(server):
    tool = server.tool("group_lines", TASK)
    check_title(tool, "Show a group's lines")
    check_read_annotations(tool)


def test_group_lines_description_length(server):
    check_description(server.tool("group_lines", TASK))


def test_group_lines_parameters(server):
    tool = server.tool("group_lines", TASK)
    check_plain(tool, "scan_id", "string", pattern="^s_[0-9a-f]{16}$")
    check_plain(tool, "group_id", "string", pattern="^[0-9a-f]{12}$")
    check_plain(tool, "limit", "integer", minimum=1, maximum=200, default=50)
    check_plain(tool, "offset", "integer", minimum=0, default=0)
    assert required_of(tool) == {"scan_id", "group_id"}, (
        f"group_lines: scan_id and group_id are required, got {sorted(required_of(tool))}"
    )


def test_group_lines_output_schema(server):
    tool = server.tool("group_lines", TASK)
    fields = output_fields(tool)
    want = {"scan_id", "group_id", "pattern", "lines", "total", "shown", "note"}
    assert want <= fields, f"group_lines: the output schema lacks {sorted(want - fields)}"
    line = output_fields(tool, "lines")
    assert {"file", "line", "time", "text"} <= line, (
        f"group_lines: a line lacks {sorted({'file', 'line', 'time', 'text'} - line)}"
    )


GOOD_ID = "s_0123456789abcdef"


@pytest.mark.parametrize("args, why", [
    ({"scan_id": "scan-1", "group_id": TOP}, "scan_id matches ^s_[0-9a-f]{16}$"),
    ({"scan_id": "s_0123456789ABCDEF", "group_id": TOP}, "scan_id is lowercase hex"),
    ({"scan_id": GOOD_ID, "group_id": "top"}, "group_id matches ^[0-9a-f]{12}$"),
    ({"scan_id": GOOD_ID}, "group_id is required"),
    ({"group_id": TOP}, "scan_id is required"),
    ({"scan_id": GOOD_ID, "group_id": TOP, "limit": 0}, "limit is at least 1"),
    ({"scan_id": GOOD_ID, "group_id": TOP, "limit": 201}, "limit is at most 200"),
    ({"scan_id": GOOD_ID, "group_id": TOP, "offset": -1}, "offset is 0 or more"),
    ({"scan_id": GOOD_ID, "group_id": TOP, "surprise": 1}, "group_lines has no parameter named surprise"),
], ids=["scan-id-shape", "scan-id-uppercase", "group-id-shape", "no-group-id", "no-scan-id",
        "limit-0", "limit-201", "offset-negative", "unknown-argument"])
def test_group_lines_refuses_bad_arguments(server, args, why):
    server.tool("group_lines", TASK)
    refused_by_schema(server.call("group_lines", args), why)


@pytest.mark.parametrize("call_id", calls_for("group_lines"))
def test_group_lines_answers(servers, call_id):
    running = servers[CALLS[call_id]["root"]]
    running.tool("group_lines", TASK)
    check_answer(running, call_id)


@pytest.mark.parametrize("call_id", calls_for("group_lines", "error"))
def test_group_lines_refuses_a_group_the_scan_does_not_keep(server, call_id):
    server.tool("group_lines", TASK)
    check_error(server, call_id)


def test_unknown_scan_id(server):
    server.tool("group_lines", TASK)
    reply = server.call("group_lines", {"scan_id": GOOD_ID, "group_id": TOP})
    tool_error(reply, e6(GOOD_ID), server.root)


def test_a_scan_id_expires(short_server):
    short_server.tool("group_lines", TASK)
    scan_id = short_server.scan({"path": APP, "min_level": "any"})
    args = {"scan_id": scan_id, "group_id": TOP, "limit": 1}
    ok(short_server.call("group_lines", args))
    time.sleep(3)
    tool_error(short_server.call("group_lines", args), e6(scan_id), short_server.root)


def test_the_21st_scan_drops_the_first(server):
    server.tool("group_lines", TASK)
    ids = [server.scan({"path": APP, "min_level": "any"}) for _ in range(21)]
    first = {"scan_id": ids[0], "group_id": TOP, "limit": 1}
    tool_error(server.call("group_lines", first), e6(ids[0]), server.root)
    for scan_id in (ids[1], ids[20]):
        ok(server.call("group_lines", {"scan_id": scan_id, "group_id": TOP, "limit": 1}))


def test_scans_made_at_once_are_all_kept_up_to_the_cap(server):
    server.tool("group_lines", TASK)
    replies = server.call_many("summarize_logs", [{"path": APP, "min_level": "any"}] * 25)
    ids = [ok(reply)["scan_id"] for reply in replies]
    assert len(set(ids)) == 25 and all(SCAN_ID_RE.match(i) for i in ids), (
        "25 scans made at the same time must give 25 different scan_ids"
    )
    kept = [i for i in ids if not server.call("group_lines", {"scan_id": i, "group_id": TOP, "limit": 1}).is_error]
    assert len(kept) == 20, (
        f"after 25 scans at once, exactly 20 must still answer (the cap per owner); {len(kept)} did. "
        "The scan store must be safe under concurrent calls."
    )


def test_group_lines_reads_the_scan_not_the_folder(tmp_path):
    """Files added after the scan don't change its groups: group_lines doesn't scan again."""
    entry = {"path": "logs/worker.log", "numbered": True, "repeat": 30,
             "text": ["2026-01-15T11:00:00.000Z INFO worker job {n} done"]}
    make_entry(entry, tmp_path)
    running = Server(root=tmp_path / "logs", reports=tmp_path / "reports")
    try:
        running.tool("group_lines", TASK)
        scan = ok(running.call("summarize_logs", {"min_level": "any"}))
        group = scan["groups"][0]["group_id"]
        make_entry({**entry, "path": "logs/worker-2.log"}, tmp_path)
        result = ok(running.call("group_lines", {"scan_id": scan["scan_id"], "group_id": group, "limit": 200}))
        assert result.get("total") == 30 and {line.get("file") for line in result.get("lines", [])} == {"worker.log"}, (
            "group_lines must answer from the scan it names: a file added after the scan must not "
            f"appear, got total {result.get('total')} and files "
            f"{sorted({line.get('file') for line in result.get('lines', [])})}"
        )
    finally:
        running.close()
