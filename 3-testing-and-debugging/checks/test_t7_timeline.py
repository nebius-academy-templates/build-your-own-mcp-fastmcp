"""Task 7: timeline, E11, E12, version 0.3.0 and the instructions."""

from __future__ import annotations

import re
import time

import pytest

from support import (
    CALLS, P1_INSTRUCTIONS, P3_SENTENCE, S3_LOGS, Server, calls_for, check_answer, check_description,
    check_error, check_nullable_string, check_plain, check_read_annotations, check_title, e6, ok,
    output_fields, p2_sentence, refused_by_schema, required_of, tool_error,
)

TASK = "Task 7 registers timeline."
APP = "pods/provisioner-2/archive/app-2026-08-30.log.gz"
GOOD_ID = "s_0123456789abcdef"


def version_tuple(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    assert match, f"the server version must look like 0.3.0, got {text!r}"
    return tuple(int(part) for part in match.groups())


def test_server_version_is_at_least_0_3_0(server):
    version = server.server_info.version
    assert version_tuple(version) >= (0, 3, 0), f"the server version must be 0.3.0 or later, got {version!r}. {TASK}"


def test_instructions_add_the_timeline_sentence(server):
    text = server.instructions or ""
    want = f"{P1_INSTRUCTIONS} {p2_sentence('15 minutes')} {P3_SENTENCE}"
    if version_tuple(server.server_info.version) < (0, 4, 0):
        assert text == want, (
            "instructions must be the practice 2 text, a space, and the timeline sentence of CONTRACT.md, "
            f"Instructions.\nexpected: {want!r}\ngot:      {text!r}"
        )
    else:
        assert text.startswith(want), "later instructions must keep the practice 3 text first"
    assert len(text) <= 1000, f"instructions must be at most 1,000 characters, got {len(text)}"


def test_timeline_title_and_annotations(server):
    tool = server.tool("timeline", TASK)
    check_title(tool, "Timeline of matching lines")
    check_read_annotations(tool)


def test_timeline_description_length(server):
    check_description(server.tool("timeline", TASK))


def test_timeline_parameters(server):
    tool = server.tool("timeline", TASK)
    check_plain(tool, "scan_id", "string", pattern="^s_[0-9a-f]{16}$")
    check_nullable_string(tool, "pattern", minLength=1, maxLength=200)
    check_plain(tool, "bucket_minutes", "integer", minimum=1, maximum=1440, default=60)
    check_nullable_string(tool, "value_pattern", minLength=1, maxLength=200)
    assert required_of(tool) == {"scan_id"}, f"timeline: only scan_id is required, got {sorted(required_of(tool))}"


def test_timeline_output_schema(server):
    tool = server.tool("timeline", TASK)
    fields = output_fields(tool)
    want = {"scan_id", "pattern", "value_pattern", "bucket_minutes", "start", "end", "total", "buckets"}
    assert want <= fields, f"timeline: the output schema lacks {sorted(want - fields)}"
    bucket = output_fields(tool, "buckets")
    want_bucket = {"start", "count", "value_count", "min", "median", "max"}
    assert want_bucket <= bucket, f"timeline: a bucket lacks {sorted(want_bucket - bucket)}"


@pytest.mark.parametrize("args, why", [
    ({}, "scan_id is required"),
    ({"scan_id": "scan-1"}, "scan_id matches ^s_[0-9a-f]{16}$"),
    ({"scan_id": GOOD_ID, "bucket_minutes": 0}, "bucket_minutes is at least 1"),
    ({"scan_id": GOOD_ID, "bucket_minutes": 1441}, "bucket_minutes is at most 1,440"),
    ({"scan_id": GOOD_ID, "pattern": ""}, "pattern is at least 1 character"),
    ({"scan_id": GOOD_ID, "value_pattern": "x" * 201}, "value_pattern is at most 200 characters"),
    ({"scan_id": GOOD_ID, "surprise": 1}, "timeline has no parameter named surprise"),
], ids=["no-scan-id", "scan-id-shape", "bucket-0", "bucket-1441", "pattern-empty", "value-pattern-long",
        "unknown-argument"])
def test_timeline_refuses_bad_arguments(server, args, why):
    server.tool("timeline", TASK)
    refused_by_schema(server.call("timeline", args), why)


@pytest.mark.parametrize("call_id", calls_for("timeline"))
def test_timeline_answers(servers, call_id):
    running = servers[CALLS[call_id]["root"]]
    running.tool("timeline", TASK)
    result = check_answer(running, call_id)
    assert result.get("total") == sum(b.get("count", 0) for b in result.get("buckets", [])), (
        f"timeline {call_id}: total must equal the sum of the bucket counts"
    )


@pytest.mark.parametrize("call_id", calls_for("timeline", "error"))
def test_timeline_refusals(servers, call_id):
    running = servers[CALLS[call_id]["root"]]
    running.tool("timeline", TASK)
    check_error(running, call_id)


def test_timeline_on_an_unknown_scan(server):
    server.tool("timeline", TASK)
    tool_error(server.call("timeline", {"scan_id": GOOD_ID}), e6(GOOD_ID), server.root)


def test_timeline_on_an_expired_scan(tmp_path):
    running = Server("--scan-ttl", "2", root=S3_LOGS, reports=tmp_path / "reports", task="Task 2 of practice 2")
    try:
        running.tool("timeline", TASK)
        scan_id = running.scan({"path": APP})
        ok(running.call("timeline", {"scan_id": scan_id, "bucket_minutes": 1440}))
        time.sleep(3)
        tool_error(running.call("timeline", {"scan_id": scan_id}), e6(scan_id), running.root)
    finally:
        running.close()
