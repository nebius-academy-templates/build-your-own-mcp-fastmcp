"""Task 1: your unit tests for the formats and the grouping steps."""

from __future__ import annotations

import tomllib

from support import SERVER, check_layer, need_own_project

TASK = "Task 1 writes the unit tests (see the practice lesson)."


def test_the_server_project_has_a_dev_group_with_pytest():
    need_own_project()
    project = tomllib.loads((SERVER / "pyproject.toml").read_text(encoding="utf-8"))
    dev = project.get("dependency-groups", {}).get("dev", [])
    names = {entry.split("=")[0].split(">")[0].split("<")[0].split("[")[0].strip().lower()
             for entry in dev if isinstance(entry, str)}
    assert {"pytest", "pytest-asyncio"} <= names, (
        f"solution/pyproject.toml needs a dev dependency group with pytest and pytest-asyncio, got {dev}. {TASK}"
    )


def test_unit_tests_run_and_pass():
    check_layer("unit", 4, TASK)
