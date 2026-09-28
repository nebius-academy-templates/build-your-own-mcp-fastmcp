"""Task 2: the server object, its command line and stdio."""

from __future__ import annotations

import os
import re
import subprocess

from support import S3_LOGS, Server, server_command

INSTRUCTIONS = (
    "Log Triage reads log files under one folder. Start with list_logs to see what is there. "
    "Use summarize_logs on a file or folder, with since and until when you know the time, to get "
    "counts and message groups instead of raw lines. Use search_logs to find the lines that match a "
    "pattern. Record a conclusion with save_finding and cite a file and line for every piece of "
    "evidence. All times are UTC."
)


def version_tuple(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    assert match, f"the server version must look like 0.1.0, got {text!r}"
    return tuple(int(part) for part in match.groups())


def run_once(args: list[str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    return subprocess.run(
        server_command() + args, stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=180, env=env,
    )


def test_server_starts_over_stdio(server):
    server.require()
    assert server.protocol_version, "the server connected but no protocol version was agreed"


def test_server_name_is_log_triage(server):
    assert server.server_info.name == "log-triage", (
        f"the server name must be 'log-triage', got {server.server_info.name!r}"
    )


def test_server_version_is_at_least_0_1_0(server):
    assert version_tuple(server.server_info.version) >= (0, 1, 0), (
        f"the server version must be 0.1.0 or later, got {server.server_info.version!r}"
    )


def test_instructions_match_the_contract(server):
    text = server.instructions
    assert text, "the server publishes no instructions; CONTRACT.md, Instructions, gives the text"
    if version_tuple(server.server_info.version) < (0, 2, 0):
        assert len(text) <= 512, f"instructions must be at most 512 characters, got {len(text)}"
        assert text == INSTRUCTIONS, (
            "instructions must be exactly the text in CONTRACT.md, Instructions.\n"
            f"expected: {INSTRUCTIONS!r}\ngot:      {text!r}"
        )
    else:
        assert text.startswith(INSTRUCTIONS), "later instructions must keep the practice 1 text first"


def test_missing_root_exits_with_code_2(tmp_path):
    missing = tmp_path / "no such folder"
    run = run_once(["--root", str(missing)])
    line = f'log root "{missing}" is not a readable folder'
    assert line in run.stderr.splitlines(), (
        f"with a missing --root the server must print this line on stderr:\n{line}\n"
        f"stderr was:\n{run.stderr[-800:]}"
    )
    assert run.returncode == 2, f"with a missing --root the exit code must be 2, got {run.returncode}"
    assert run.stdout == "", f"nothing may go to stdout, got {run.stdout[:200]!r}"


def test_root_that_is_a_file_exits_with_code_2(tmp_path):
    a_file = tmp_path / "not a folder.log"
    a_file.write_text("x\n")
    run = run_once(["--root", str(a_file)])
    line = f'log root "{a_file}" is not a readable folder'
    assert line in run.stderr.splitlines(), (
        f"with a file as --root the server must print this line on stderr:\n{line}\n"
        f"stderr was:\n{run.stderr[-800:]}"
    )
    assert run.returncode == 2, f"with a file as --root the exit code must be 2, got {run.returncode}"


def test_server_accepts_reports_and_read_only(tmp_path):
    running = Server("--read-only", root=S3_LOGS, reports=tmp_path / "reports")
    try:
        running.require()
        running.tools()
    finally:
        running.close()
