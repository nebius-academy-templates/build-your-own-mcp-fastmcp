"""Task 4: read_lines: the lines around one line, clipped to the file, E8 and E10."""

from __future__ import annotations

import pytest

from support import (
    CALLS, calls_for, check_answer, check_description, check_error, check_plain,
    check_read_annotations, check_title, output_fields, refused_by_schema, required_of,
)

TASK = "Task 4 registers read_lines."
APP = "pods/provisioner-2/archive/app-2026-08-30.log.gz"


def test_read_lines_title_and_annotations(server):
    tool = server.tool("read_lines", TASK)
    check_title(tool, "Read lines around a line")
    check_read_annotations(tool)


def test_read_lines_description_length(server):
    check_description(server.tool("read_lines", TASK))


def test_read_lines_parameters(server):
    tool = server.tool("read_lines", TASK)
    check_plain(tool, "path", "string", maxLength=500)
    check_plain(tool, "line", "integer", minimum=1)
    check_plain(tool, "before", "integer", minimum=0, maximum=50, default=5)
    check_plain(tool, "after", "integer", minimum=0, maximum=200, default=20)
    assert required_of(tool) == {"path", "line"}, (
        f"read_lines: path and line are required, got {sorted(required_of(tool))}"
    )


def test_read_lines_output_schema(server):
    tool = server.tool("read_lines", TASK)
    fields = output_fields(tool)
    want = {"file", "start", "end", "total_lines", "lines"}
    assert want <= fields, f"read_lines: the output schema lacks {sorted(want - fields)}"
    line = output_fields(tool, "lines")
    assert {"line", "text"} <= line, f"read_lines: a line lacks {sorted({'line', 'text'} - line)}"


@pytest.mark.parametrize("args, why", [
    ({"path": APP}, "line is required"),
    ({"line": 1}, "path is required"),
    ({"path": APP, "line": 0}, "line is 1 or more"),
    ({"path": APP, "line": 1, "before": 51}, "before is at most 50"),
    ({"path": APP, "line": 1, "before": -1}, "before is 0 or more"),
    ({"path": APP, "line": 1, "after": 201}, "after is at most 200"),
    ({"path": "x" * 501, "line": 1}, "path is at most 500 characters"),
    ({"path": APP, "line": 1, "surprise": 1}, "read_lines has no parameter named surprise"),
], ids=["no-line", "no-path", "line-0", "before-51", "before-negative", "after-201",
        "path-too-long", "unknown-argument"])
def test_read_lines_refuses_bad_arguments(server, args, why):
    server.tool("read_lines", TASK)
    refused_by_schema(server.call("read_lines", args), why)


@pytest.mark.parametrize("call_id", calls_for("read_lines"))
def test_read_lines_answers(servers, call_id):
    running = servers[CALLS[call_id]["root"]]
    running.tool("read_lines", TASK)
    check_answer(running, call_id)


@pytest.mark.parametrize("call_id", calls_for("read_lines", "error"))
def test_read_lines_refuses_past_the_end_and_folders(server, call_id):
    server.tool("read_lines", TASK)
    check_error(server, call_id)
