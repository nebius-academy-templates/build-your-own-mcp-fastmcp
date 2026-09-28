"""Task 6: search_logs: matching lines, their order, window, level and paging."""

from __future__ import annotations

import pytest

from support import (
    CALLS, calls_for, check_answer, check_description, check_enum, check_nullable_string,
    check_plain, check_read_annotations, check_title, output_fields, refused_by_schema,
    required_of, tool_error,
)

TASK = "Task 6 registers search_logs."
LEVELS = ["any", "debug", "info", "warning", "error", "critical"]


def test_search_logs_title_and_annotations(server):
    tool = server.tool("search_logs", TASK)
    check_title(tool, "Search logs")
    check_read_annotations(tool)


def test_search_logs_description_length(server):
    check_description(server.tool("search_logs", TASK))


def test_search_logs_parameters(server):
    tool = server.tool("search_logs", TASK)
    check_plain(tool, "path", "string", maxLength=500, default=".")
    check_plain(tool, "pattern", "string", minLength=1, maxLength=200)
    check_nullable_string(tool, "since", maxLength=40)
    check_nullable_string(tool, "until", maxLength=40)
    check_enum(tool, "min_level", LEVELS, default="any")
    check_plain(tool, "limit", "integer", minimum=1, maximum=200, default=50)
    check_plain(tool, "offset", "integer", minimum=0, default=0)
    assert required_of(tool) == {"pattern"}, (
        f"search_logs: only pattern is required, got {sorted(required_of(tool))}"
    )


def test_search_logs_output_schema(server):
    tool = server.tool("search_logs", TASK)
    fields = output_fields(tool)
    want = {"path", "pattern", "matches", "total", "shown", "note"}
    assert want <= fields, f"search_logs: the output schema lacks {sorted(want - fields)}"
    match = output_fields(tool, "matches")
    want_match = {"file", "line", "time", "level", "text"}
    assert want_match <= match, f"search_logs: a match lacks {sorted(want_match - match)}"


@pytest.mark.parametrize("args, why", [
    ({}, "pattern is required"),
    ({"pattern": ""}, "pattern is at least 1 character"),
    ({"pattern": "x" * 201}, "pattern is at most 200 characters"),
    ({"pattern": "x", "min_level": "fatal"}, "min_level is one of " + ", ".join(LEVELS)),
    ({"pattern": "x", "limit": 201}, "limit is at most 200"),
    ({"pattern": "x", "offset": -1}, "offset is 0 or more"),
    ({"pattern": "x", "surprise": 1}, "search_logs has no parameter named surprise"),
], ids=["no-pattern", "empty-pattern", "pattern-too-long", "min-level-fatal", "limit-201",
        "offset-negative", "unknown-argument"])
def test_search_logs_refuses_bad_arguments(server, args, why):
    server.tool("search_logs", TASK)
    refused_by_schema(server.call("search_logs", args), why)


@pytest.mark.parametrize("call_id", calls_for("search_logs"))
def test_search_logs_answers(servers, call_id):
    check_answer(servers[CALLS[call_id]["root"]], call_id)


@pytest.mark.parametrize("path", ["..", "/etc"])
def test_search_logs_refuses_a_path_outside_the_root(server, path):
    server.tool("search_logs", TASK)
    tool_error(server.call("search_logs", {"path": path, "pattern": "x"}), "the path is outside the log root")
