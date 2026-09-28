"""Task 4: the probe, a scripted stdio client, and its transcript (probe-expected.md)."""

from __future__ import annotations

import re

from support import S3_LOGS, e1, e6, run_probe

TASK = "Task 4 writes solution/scripts/probe.py (see the practice lesson and probe-expected.md)."
SCAN = r"s_[0-9a-f]{16}"
STEP = re.compile(r"^step (\d+) ([a-z-]+): ([a-z_]+) -> (.*)$")


def probe_steps() -> dict[str, tuple[str, str]]:
    run = run_probe(S3_LOGS)
    assert run.returncode == 0, (
        f"the probe must exit 0, it exited {run.returncode}. {TASK}\nstdout:\n{run.stdout[-800:]}\nstderr:\n{run.stderr[-800:]}"
    )
    steps = {}
    for line in run.stdout.splitlines():
        m = STEP.match(line.strip())
        if m:
            steps[m.group(2)] = (m.group(3), m.group(4))
    want = ["out-of-order", "scan", "expired", "unknown-argument", "hostile-path"]
    assert list(steps) == want, (
        f"the probe must print the five steps of probe-expected.md in order, as "
        f"'step <k> <name>: <tool> -> <outcome>'; found {list(steps)}.\nstdout:\n{run.stdout[-800:]}"
    )
    return steps


def outcome(steps: dict, name: str, tool: str) -> str:
    got_tool, text = steps[name]
    assert got_tool == tool, f"probe step {name}: the tool must be {tool}, got {got_tool}"
    return text


def test_the_probe_runs_every_step_in_order():
    probe_steps()


def test_the_probe_transcript_matches_the_expected_outcomes():
    steps = probe_steps()
    first = outcome(steps, "out-of-order", "group_lines")
    m = re.fullmatch("tool error: " + re.escape(e6("ID")).replace("ID", f"({SCAN})"), first)
    assert m, f"step out-of-order: expected a tool error with E6 for a scan_id nobody made, got {first!r}"
    scan = re.fullmatch(f"ok scan_id=({SCAN})", outcome(steps, "scan", "summarize_logs"))
    assert scan, f"step scan: expected 'ok scan_id=<id>', got {steps['scan'][1]!r}"
    expired = outcome(steps, "expired", "group_lines")
    assert expired == f"tool error: {e6(scan.group(1))}", (
        f"step expired: expected E6 for the scan of step 2 ({scan.group(1)}), got {expired!r}"
    )
    assert outcome(steps, "unknown-argument", "list_logs") == "refused", (
        f"step unknown-argument: expected 'refused', got {steps['unknown-argument'][1]!r}"
    )
    hostile = outcome(steps, "hostile-path", "read_lines")
    assert hostile == f"tool error: {e1('../outside.log')}", f"step hostile-path: got {hostile!r}"
