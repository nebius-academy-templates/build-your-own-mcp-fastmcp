"""Task 6: path screening, symlinks, size and line caps, unreadable archives, E1 and E2."""

from __future__ import annotations

import pytest

from support import (
    CALLS, Server, calls_for, check_answer, e1, e2, fill, ok, tool_error,
)

READS = "Task 6: symlinked entries, unreadable and oversized files are skipped (CONTRACT.md, Reading logs)."
REGISTERED = {"read_lines": "Task 4 registers read_lines."}
TOOLS = {
    "list_logs": {},
    "summarize_logs": {},
    "search_logs": {"pattern": "."},
    "read_lines": {"line": 1},
}
OUTSIDE = [
    "a\x00b.log",
    "app.log\x00",
    "/etc",
    "/",
    "..",
    "../",
    "a/../../b",
    "walk/../../outside/secret.log",
    "{base}/outside/secret.log",
    "link-out.log",
    "link-in.log",
    "linkdir",
    "linkdir/secret.log",
    "walk/zz-link.log",
    "walk/sub-link",
]
MISSING = [
    "nope",
    "nope/missing.log",
    "walk/missing.log",
    "{root}/missing.log",
]


def hostile_calls(tool: str) -> list[str]:
    return [call_id for call_id in calls_for(tool) if CALLS[call_id]["root"] == "hostile"]


@pytest.mark.parametrize("path", OUTSIDE, ids=[repr(p)[1:-1] for p in OUTSIDE])
@pytest.mark.parametrize("tool", list(TOOLS))
def test_outside_the_root_or_through_a_symlink(hostile_server, hostile, tool, path):
    hostile_server.tool(tool, REGISTERED.get(tool))
    path = fill(path, {"base": str(hostile.base), "root": str(hostile.root)})
    reply = hostile_server.call(tool, {**TOOLS[tool], "path": path})
    tool_error(reply, e1(path), hostile.root)


@pytest.mark.parametrize("path", MISSING)
@pytest.mark.parametrize("tool", list(TOOLS))
def test_missing_path(hostile_server, hostile, tool, path):
    hostile_server.tool(tool, REGISTERED.get(tool))
    path = fill(path, {"root": str(hostile.root)})
    reply = hostile_server.call(tool, {**TOOLS[tool], "path": path})
    tool_error(reply, e2(path), hostile.root)


@pytest.mark.parametrize("call_id", hostile_calls("summarize_logs"))
def test_scans_skip_what_they_cannot_read(hostile_server, call_id):
    check_answer(hostile_server, call_id, READS)


@pytest.mark.parametrize("call_id", hostile_calls("search_logs"))
def test_searches_skip_what_they_cannot_read(hostile_server, call_id):
    check_answer(hostile_server, call_id, READS)


@pytest.mark.parametrize("call_id", hostile_calls("list_logs"))
def test_listing_leaves_symlinks_out(hostile_server, call_id):
    check_answer(hostile_server, call_id, READS)


def test_a_log_root_under_a_symlinked_folder_works(hostile, tmp_path):
    """The root itself may sit under symlinks; only the part below it is screened."""
    running = Server(root=hostile.base / "root-link", reports=tmp_path / "reports")
    try:
        for call_id in ("list-hostile-walk", "summarize-hostile-walk", "search-hostile-walk"):
            check_answer(running, call_id, "CONTRACT.md, Paths: the log root may sit under symlinks.")
    finally:
        running.close()


def scan_group(server: Server, path: str) -> dict:
    result = ok(server.call("summarize_logs", {"path": path, "min_level": "any"}))
    assert result["groups"], f"summarize_logs found no group in {path}"
    return {"scan_id": result["scan_id"], "group_id": result["groups"][0]["group_id"]}


def test_group_lines_refuses_a_file_replaced_by_a_symlink(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    inside = root / "app.log"
    outside = tmp_path / "outside.log"
    inside.write_text("2026-01-15T10:00:00.000Z ERROR worker stopped\n")
    outside.write_text("AUDIT_OUTSIDE_MARKER\n")
    running = Server(root=root, reports=tmp_path / "reports")
    try:
        args = scan_group(running, "app.log")
        inside.unlink()
        inside.symlink_to(outside)
        tool_error(running.call("group_lines", args), e1("app.log"), root)
    finally:
        running.close()


def test_group_lines_refuses_a_parent_replaced_by_a_symlink(tmp_path):
    root = tmp_path / "logs"
    inside_dir = root / "nested"
    outside_dir = tmp_path / "outside"
    inside_dir.mkdir(parents=True)
    outside_dir.mkdir()
    (inside_dir / "app.log").write_text("2026-01-15T10:00:00.000Z ERROR worker stopped\n")
    (outside_dir / "app.log").write_text("AUDIT_OUTSIDE_MARKER\n")
    running = Server(root=root, reports=tmp_path / "reports")
    try:
        args = scan_group(running, "nested/app.log")
        inside_dir.rename(root / "original")
        inside_dir.symlink_to(outside_dir)
        tool_error(running.call("group_lines", args), e1("nested/app.log"), root)
    finally:
        running.close()
