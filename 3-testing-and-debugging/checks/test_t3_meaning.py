"""Task 3: your meaning tests against facts.json, the whole suite, and the facts on your server."""

from __future__ import annotations

import gzip
import shutil

import pytest

from support import (
    FACTS, S3_LOGS, Server, check_layer, need_own_project, ok, run_own_tests, same,
)

TASK = "Task 3 writes the meaning tests (see the practice lesson)."
IGNORED = {"scan_id", "expires_at", "path"}


def test_meaning_tests_run_and_pass():
    check_layer("meaning", 3, TASK)


def test_the_whole_suite_passes_with_at_least_ten_tests():
    need_own_project()
    run = run_own_tests("tests")
    assert run.returncode == 0, f"uv run --project solution pytest must pass; failed: {run.failed[:10]}\n{run.tail()}"
    assert run.tests >= 10, f"your suite must hold at least 10 tests across its layers, it has {run.tests}. {TASK}"


@pytest.mark.parametrize("fact", FACTS["files"], ids=[f["path"].rsplit("/", 1)[-1] for f in FACTS["files"]])
def test_the_server_agrees_with_facts_json(server, fact):
    result = ok(server.call("summarize_logs", {"path": fact["path"], "min_level": "any", "limit": 3}))
    where = f"summarize_logs on {fact['path']}"
    same(result.get("lines_scanned"), fact["lines"], f"{where}: lines_scanned")
    same(result.get("by_level"), fact["by_level"], f"{where}: by_level")
    same(result.get("first_seen"), fact["first_seen"], f"{where}: first_seen")
    same(result.get("last_seen"), fact["last_seen"], f"{where}: last_seen")
    got = [{"group_id": g.get("group_id"), "count": g.get("count")} for g in result.get("groups", [])]
    same(got, fact["top_groups"], f"{where}: the first three groups")
    window = fact.get("window")
    if window:
        result = ok(server.call("summarize_logs", {"path": fact["path"], "since": window["since"],
                                                   "until": window["until"], "min_level": "any"}))
        same(result.get("lines_in_window"), window["lines_in_window"],
             f"{where} from {window['since']} to {window['until']}: lines_in_window")
    if "run_headers" in fact:
        found = ok(server.call("search_logs", {"path": fact["path"], "pattern": "^=== run \\S+ ===$", "limit": 1}))
        same(found.get("total"), fact["run_headers"], f"search_logs for run headers in {fact['path']}: total")


@pytest.mark.parametrize("path", FACTS["gz_vs_plain"])
def test_a_gz_file_reads_like_its_plain_copy(tmp_path, path):
    root = tmp_path / "logs"
    (root / "gz").mkdir(parents=True)
    (root / "plain").mkdir()
    name = path.rsplit("/", 1)[-1]
    shutil.copyfile(S3_LOGS / path, root / "gz" / name)
    (root / "plain" / name[: -len(".gz")]).write_bytes(gzip.decompress((S3_LOGS / path).read_bytes()))
    running = Server(root=root, reports=tmp_path / "reports")
    try:
        results = {}
        for side in ("gz", "plain"):
            full = ok(running.call("summarize_logs", {"path": side, "min_level": "any", "limit": 100}))
            for group in full.get("groups", []):
                group.pop("files", None)
                (group.get("example") or {}).pop("file", None)
            results[side] = {k: v for k, v in full.items() if k not in IGNORED}
        same(results["plain"], results["gz"], f"summarize_logs on the plain copy of {name} against the .gz")
    finally:
        running.close()
