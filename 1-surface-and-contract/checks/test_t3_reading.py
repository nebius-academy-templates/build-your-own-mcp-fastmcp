"""Task 3: reading logs by docs/log-formats.md, seen through a first list_logs.

Times, levels, messages and groups are checked through summarize_logs and
search_logs in the later check files.
"""

from __future__ import annotations

import pytest

from support import CALLS, EXPECTED

TASK = "Task 3 registers a first list_logs so the checks can see the formats your reader detects."


def listed(server, path: str | None) -> list[dict]:
    server.tool("list_logs", TASK)
    reply = server.call("list_logs", {} if path is None else {"path": path})
    assert reply.error is None and not reply.is_error, f"{reply.label()} failed: {reply.summary()}"
    result = reply.structured
    assert isinstance(result, dict) and isinstance(result.get("files"), list), (
        f"{reply.label()} must return an object whose 'files' lists the files "
        f"(CONTRACT.md, list_logs), got {result!r:.200}"
    )
    return result["files"]


def test_list_logs_is_registered(server):
    server.tool("list_logs", TASK)


@pytest.mark.parametrize("path", list(EXPECTED["formats"]))
def test_format_of_one_file(server, path):
    files = listed(server, path)
    got = [(f.get("path"), f.get("format")) for f in files]
    assert got == [(path, EXPECTED["formats"][path])], (
        f"list_logs on one file must list that file with its format; expected "
        f"{[(path, EXPECTED['formats'][path])]}, got {got}"
    )


def test_formats_of_a_folder_in_byte_order(tree_server):
    files = listed(tree_server, None)
    got = [(f.get("path"), f.get("format")) for f in files]
    want = [(f["path"], f["format"]) for f in CALLS["list-tree"]["result"]["files"]]
    assert got == want, (
        "list_logs on a folder must list every regular file below it, in byte order of the "
        "relative path, skipping names that start with '.', each with its format.\n"
        f"expected: {want}\ngot:      {got}"
    )
