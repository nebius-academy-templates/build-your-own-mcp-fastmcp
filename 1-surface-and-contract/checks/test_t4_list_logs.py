"""Task 4: list_logs to the contract: schema, annotations, output model, paging."""

from __future__ import annotations

import pytest

from support import (
    CALLS, calls_for, check_answer, check_description, check_plain, check_read_annotations,
    check_title, output_fields, refused_by_schema, required_of, tool_error,
)

TASK = "Task 3 registers list_logs and task 4 completes it."


def test_list_logs_title_and_annotations(server):
    tool = server.tool("list_logs", TASK)
    check_title(tool, "List log files")
    check_read_annotations(tool)


def test_list_logs_description_length(server):
    check_description(server.tool("list_logs", TASK))


def test_list_logs_parameters(server):
    tool = server.tool("list_logs", TASK)
    check_plain(tool, "path", "string", maxLength=500, default=".")
    check_plain(tool, "limit", "integer", minimum=1, maximum=500, default=50)
    check_plain(tool, "offset", "integer", minimum=0, default=0)
    assert required_of(tool) == set(), f"list_logs: no parameter is required, got {sorted(required_of(tool))}"


def test_list_logs_output_schema(server):
    tool = server.tool("list_logs", TASK)
    fields = output_fields(tool)
    assert {"path", "files", "total", "shown", "note"} <= fields, (
        f"list_logs: the output schema must name path, files, total, shown and note, got {sorted(fields)}"
    )
    items = output_fields(tool, "files")
    assert {"path", "size_bytes", "compressed", "format"} <= items, (
        f"list_logs: each file must name path, size_bytes, compressed and format, got {sorted(items)}"
    )


@pytest.mark.parametrize("args, why", [
    ({"limit": 0}, "limit is at least 1"),
    ({"limit": 501}, "limit is at most 500"),
    ({"offset": -1}, "offset is 0 or more"),
    ({"path": "x" * 501}, "path is at most 500 characters"),
    ({"surprise": 1}, "list_logs has no parameter named surprise"),
], ids=["limit-0", "limit-501", "offset-negative", "path-too-long", "unknown-argument"])
def test_list_logs_refuses_bad_arguments(server, args, why):
    server.tool("list_logs", TASK)
    refused_by_schema(server.call("list_logs", args), why)


@pytest.mark.parametrize("call_id", calls_for("list_logs"))
def test_list_logs_answers(servers, call_id):
    check_answer(servers[CALLS[call_id]["root"]], call_id)


@pytest.mark.parametrize("path", ["..", "../docs", "/etc"])
def test_list_logs_refuses_a_path_outside_the_root(server, path):
    server.tool("list_logs", TASK)
    tool_error(server.call("list_logs", {"path": path}), "the path is outside the log root")
