"""Task 2: your protocol and flow tests, with FastMCP's in-process client."""

from __future__ import annotations

from support import check_layer

TASK = "Task 2 writes the protocol and flow tests (see the practice lesson)."


def test_protocol_tests_run_and_pass():
    check_layer("protocol", 3, TASK)


def test_flow_tests_run_and_pass():
    check_layer("flow", 1, TASK)
