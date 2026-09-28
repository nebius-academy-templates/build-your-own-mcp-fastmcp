"""Task 6: --log-level, one stderr line per call at debug, stdout that stays protocol-only."""

from __future__ import annotations

import re
import subprocess
from collections import Counter

import pytest

from support import FACTS, S3_LOGS, Server, child_env, ok, raw_exchange, same, server_command

TASK = "Task 6 adds --log-level."
FILE = FACTS["gz_vs_plain"][0]
CALLS = [
    ("tools/call", {"name": "list_logs", "arguments": {"path": FILE}}),
    ("tools/call", {"name": "summarize_logs", "arguments": {"path": FILE}}),
    ("tools/call", {"name": "search_logs", "arguments": {"path": FILE, "pattern": "quota", "limit": 1}}),
    ("tools/call", {"name": "read_lines", "arguments": {"path": FILE, "line": 3, "before": 1, "after": 1}}),
]
MARK = re.compile(r"tool=([A-Za-z_]+)")


def call_lines(stderr: str) -> Counter:
    return Counter(m.group(1) for line in stderr.splitlines() for m in [MARK.search(line)] if m)


def exchange(tmp_path, requests, *flags):
    answers, stderr = raw_exchange(S3_LOGS, tmp_path / "reports", requests, flags)
    for (method, params), answer in zip(requests, answers):
        assert "result" in answer, f"{method} {params.get('name', '')} failed: {answer.get('error')}"
        assert not answer["result"].get("isError"), f"{params.get('name')} returned a tool error: {answer['result']}"
    return stderr


def test_debug_writes_one_line_per_call(tmp_path):
    stderr = exchange(tmp_path, CALLS, "--log-level", "debug")
    got = call_lines(stderr)
    want = Counter({"list_logs": 1, "summarize_logs": 1, "search_logs": 1, "read_lines": 1})
    assert got == want, (
        f"at --log-level debug, every tools/call writes exactly one stderr line containing tool=<name> "
        f"(CONTRACT.md, Command line); for these four calls got {dict(got)}. {TASK}\nstderr:\n{stderr[-1200:]}"
    )


def test_a_refused_call_still_writes_its_line(tmp_path):
    refused = [("tools/call", {"name": "list_logs", "arguments": {"path": FILE, "surprise": 1}})]
    answers, stderr = raw_exchange(S3_LOGS, tmp_path / "reports", refused, ("--log-level", "debug"))
    answer = answers[0]
    assert "error" in answer or answer["result"].get("isError"), "list_logs with an unknown argument must be refused"
    got = call_lines(stderr)
    assert got == Counter({"list_logs": 1}), (
        f"at --log-level debug, a call the schema refuses still writes exactly one tool=<name> line "
        f"(CONTRACT.md, Logging); got {dict(got)}. {TASK}\nstderr:\n{stderr[-1200:]}"
    )


@pytest.mark.parametrize("flags", [(), ("--log-level", "info"), ("--log-level", "warning")],
                         ids=["default", "info", "warning"])
def test_no_call_lines_above_debug(tmp_path, flags):
    stderr = exchange(tmp_path, CALLS, *flags)
    assert not call_lines(stderr), (
        f"with {' '.join(flags) or 'the default level'}, no stderr line may contain tool=<name>; "
        f"got {dict(call_lines(stderr))}. {TASK}"
    )


def test_stdout_stays_protocol_only_at_debug(tmp_path):
    requests = CALLS + [
        ("tools/list", {}),
        ("resources/read", {"uri": "triage://formats"}),
        ("tools/call", {"name": "list_logs", "arguments": {"path": FILE, "surprise": 1}}),
    ]
    answers, _ = raw_exchange(S3_LOGS, tmp_path / "reports", requests, ("--log-level", "debug"))
    assert len(answers) == len(requests), "every request must get its own answer on stdout"


def test_an_unknown_level_exits_with_code_2(tmp_path):
    run = subprocess.run(server_command() + ["--root", str(S3_LOGS), "--log-level", "loud"],
                         stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=180, env=child_env())
    assert run.returncode == 2, f"--log-level loud must exit with code 2, got {run.returncode}. {TASK}"
    assert run.stdout == "", f"nothing may go to stdout, got {run.stdout[:200]!r}"


def test_a_masked_error_leaves_its_detail_on_stderr(tmp_path):
    root = tmp_path / "logs"
    root.mkdir()
    (root / "good.log").write_text("2026-01-15T10:00:00.000Z INFO api request served\n")
    (root / "bad.log.gz").write_bytes(b"this is not gzip data\n")
    plain = [("tools/call", {"name": "list_logs", "arguments": {}})]
    broken = plain + [("tools/call", {"name": "read_lines", "arguments": {"path": "bad.log.gz", "line": 1}})]
    _, before = raw_exchange(root, tmp_path / "r1", plain)
    answers, after = raw_exchange(root, tmp_path / "r2", broken)
    assert answers[-1]["result"].get("isError"), "read_lines on a .gz file that isn't gzip must be a tool error"
    assert len(after.splitlines()) > len(before.splitlines()), (
        "a masked unexpected error must write its detail to stderr (at error level, so it shows at every level)"
    )


def test_answers_hold_at_debug(tmp_path):
    running = Server("--log-level", "debug", root=S3_LOGS, reports=tmp_path / "reports", task="Task 6")
    try:
        fact = next(f for f in FACTS["files"] if f["path"] == FILE)
        result = ok(running.call("summarize_logs", {"path": FILE, "min_level": "any", "limit": 3}))
        same(result.get("lines_scanned"), fact["lines"], "summarize_logs at --log-level debug: lines_scanned")
        same(result.get("by_level"), fact["by_level"], "summarize_logs at --log-level debug: by_level")
    finally:
        running.close()
