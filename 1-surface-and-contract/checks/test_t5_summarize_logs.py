"""Task 5: summarize_logs: window, level counts, message groups, limit and note."""

from __future__ import annotations

import pytest

from support import (
    CALLS, S3_LOGS, calls_for, check_answer, check_description, check_enum, check_nullable_string,
    check_plain, check_read_annotations, check_title, output_fields, raw_lines, refused_by_schema,
    required_of, tool_error,
)

TASK = "Task 5 registers summarize_logs."
LEVELS = ["any", "debug", "info", "warning", "error", "critical"]


def test_summarize_logs_title_and_annotations(server):
    tool = server.tool("summarize_logs", TASK)
    check_title(tool, "Summarize logs")
    check_read_annotations(tool)


def test_summarize_logs_description_length(server):
    check_description(server.tool("summarize_logs", TASK))


def test_summarize_logs_parameters(server):
    tool = server.tool("summarize_logs", TASK)
    check_plain(tool, "path", "string", maxLength=500, default=".")
    check_nullable_string(tool, "since", maxLength=40)
    check_nullable_string(tool, "until", maxLength=40)
    check_enum(tool, "min_level", LEVELS, default="warning")
    check_plain(tool, "limit", "integer", minimum=1, maximum=100, default=20)
    assert required_of(tool) == set(), f"summarize_logs: no parameter is required, got {sorted(required_of(tool))}"


def test_summarize_logs_output_schema(server):
    tool = server.tool("summarize_logs", TASK)
    fields = output_fields(tool)
    want = {"path", "since", "until", "min_level", "files_scanned", "skipped", "lines_scanned",
            "lines_in_window", "first_seen", "last_seen", "by_level", "groups", "total_groups",
            "shown", "note"}
    assert want <= fields, f"summarize_logs: the output schema lacks {sorted(want - fields)}"
    group = output_fields(tool, "groups")
    want_group = {"group_id", "format", "level", "pattern", "count", "first_seen", "last_seen",
                  "file_count", "files", "example"}
    assert want_group <= group, f"summarize_logs: a group lacks {sorted(want_group - group)}"
    example = output_fields(tool, "groups", "example")
    assert {"file", "line", "text"} <= example, f"summarize_logs: example lacks {sorted({'file', 'line', 'text'} - example)}"


@pytest.mark.parametrize("args, why", [
    ({"min_level": "fatal"}, "min_level is one of " + ", ".join(LEVELS)),
    ({"limit": 0}, "limit is at least 1"),
    ({"limit": 101}, "limit is at most 100"),
    ({"since": "2026-01-01T00:00:00.000000000000000000000000000Z"}, "since is at most 40 characters"),
    ({"surprise": 1}, "summarize_logs has no parameter named surprise"),
], ids=["min-level-fatal", "limit-0", "limit-101", "since-too-long", "unknown-argument"])
def test_summarize_logs_refuses_bad_arguments(server, args, why):
    server.tool("summarize_logs", TASK)
    refused_by_schema(server.call("summarize_logs", args), why)


@pytest.mark.parametrize("call_id", calls_for("summarize_logs"))
def test_summarize_logs_answers(servers, call_id):
    check_answer(servers[CALLS[call_id]["root"]], call_id)


def test_min_level_any_includes_unknown(server):
    server.tool("summarize_logs", TASK)
    levels = {g["level"] for g in check_answer(server, "summarize-redis-any")["groups"]}
    assert "unknown" in levels, "min_level any must include groups of level unknown"
    levels = {g["level"] for g in check_answer(server, "summarize-redis-debug")["groups"]}
    assert "unknown" not in levels, "min_level debug must leave out groups of level unknown"


def test_no_log_line_outside_example(server):
    server.tool("summarize_logs", TASK)
    call = CALLS["summarize-app-any"]
    result = check_answer(server, "summarize-app-any")
    lines = set(raw_lines(S3_LOGS / call["args"]["path"]))

    def walk(value, where):
        if isinstance(value, dict):
            for key, item in value.items():
                if key != "example":
                    walk(item, f"{where}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{where}[{index}]")
        elif isinstance(value, str):
            assert value not in lines, f"summarize_logs{where} holds a raw log line; only example.text may"

    walk(result, "")


@pytest.mark.parametrize("path", ["..", "/etc"])
def test_summarize_logs_refuses_a_path_outside_the_root(server, path):
    server.tool("summarize_logs", TASK)
    tool_error(server.call("summarize_logs", {"path": path}), "the path is outside the log root")
