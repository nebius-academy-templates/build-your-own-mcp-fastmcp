"""Task 5: resources: triage://formats, triage://reports, the two templates, not-found, freshness."""

from __future__ import annotations

import time

import pytest

from support import (
    EXPECTED, S3_LOGS, Server, ok, not_found, raw_exchange,
)

TASK = "Task 5 adds the resources."
SMALL = {"path": "vms/web-01/archive/php-fpm-2026-08-30.log.gz", "min_level": "any"}
EVIDENCE = [{"file": "vms/web-01/archive/php-fpm-2026-08-30.log.gz", "line": 2, "note": "the pool starts"}]
VALID = "# Worker pool restarts at dawn\n\n- Severity: low\n- Saved: 2026-01-15T10:00:00Z\n\nA note.\n\n## Evidence\n\n- `a.log` line 1: one\n"


def by_uri(items: list[dict], key: str) -> dict[str, dict]:
    return {item.get(key): item for item in items}


def finding(title: str) -> dict:
    return {"title": title, "severity": "high", "summary": "Seen twice.", "evidence": EVIDENCE}


@pytest.fixture(scope="module")
def stocked(tmp_path_factory):
    """A server whose reports folder already holds files the list must leave out, and one it keeps."""
    base = tmp_path_factory.mktemp("stocked")
    reports = base / "reports"
    reports.mkdir()
    (reports / "README.md").write_text("# Reports\n\nFindings saved by the server.\n")
    (reports / ".hidden.md").write_text(VALID)
    (reports / "notes.txt").write_text(VALID)
    (reports / "a.b.md").write_text(VALID)
    (base / "elsewhere.md").write_text(VALID)
    (reports / "linked.md").symlink_to(base / "elsewhere.md")
    (reports / "worker-pool-restarts-at-dawn.md").write_text(VALID)
    running = Server(root=S3_LOGS, reports=reports)
    yield running
    running.close()


def test_resources_list_the_two_documents(server):
    listed = by_uri(server.resources(), "uri")
    for uri in ("triage://formats", "triage://reports"):
        assert uri in listed, f"resources/list must include {uri}, found {sorted(listed)}. {TASK}"
        assert listed[uri].get("mimeType") == "application/json", (
            f"{uri}: mimeType must be application/json, got {listed[uri].get('mimeType')!r}"
        )


def test_resource_templates_list_the_two_templates(server):
    listed = by_uri(server.templates(), "uriTemplate")
    for uri, mime in (("triage://reports/{name}", "text/markdown"), ("triage://scans/{scan_id}", "application/json")):
        assert uri in listed, f"resources/templates/list must include {uri}, found {sorted(listed)}. {TASK}"
        assert listed[uri].get("mimeType") == mime, (
            f"{uri}: mimeType must be {mime}, got {listed[uri].get('mimeType')!r}"
        )


def test_formats_document(server):
    reply = server.read("triage://formats")
    assert reply.document() == EXPECTED["formats_document"], (
        "triage://formats must list the nine formats in order, each with its levels, timestamp and "
        "the first sample line of docs/log-formats.md (CONTRACT.md, Resources).\n"
        f"expected: {EXPECTED['formats_document']}\ngot:      {reply.document()}"
    )
    assert reply.mime_type() == "application/json", f"triage://formats: mimeType {reply.mime_type()!r}"


def test_reports_document_is_empty_without_reports(tmp_path):
    running = Server(root=S3_LOGS, reports=tmp_path / "not created yet")
    try:
        reply = running.read("triage://reports")
        assert reply.document() == {"count": 0, "reports": []}, (
            f"triage://reports with no reports folder must be {{'count': 0, 'reports': []}}, got {reply.document()}"
        )
        assert reply.mime_type() == "application/json"
    finally:
        running.close()


def test_saved_findings_are_listed_and_readable(server):
    server.tool("save_finding", "Practice 1 registers save_finding.")
    empty = server.read("triage://reports").document()
    assert empty == {"count": 0, "reports": []}, f"triage://reports on an empty folder: {empty}"
    zeta = ok(server.call("save_finding", finding("Zeta cache misses")))
    alpha = ok(server.call("save_finding", {**finding("Alpha queue backlog"), "severity": "low"}))
    listed = server.read("triage://reports").document()
    want = {"count": 2, "reports": [
        {"name": "alpha-queue-backlog", "title": "Alpha queue backlog", "severity": "low", "created": alpha["created"]},
        {"name": "zeta-cache-misses", "title": "Zeta cache misses", "severity": "high", "created": zeta["created"]},
    ]}
    assert listed == want, f"triage://reports after two saves:\nexpected: {want}\ngot:      {listed}"
    reply = server.read("triage://reports/zeta-cache-misses")
    assert reply.error is None, f"triage://reports/zeta-cache-misses failed: {reply.error}"
    content = (server.reports / "zeta-cache-misses.md").read_bytes().decode("utf-8")
    assert len(reply.contents) == 1 and reply.contents[0].get("text") == content, (
        "triage://reports/{name} must return the saved file exactly"
    )
    assert reply.mime_type() == "text/markdown", f"triage://reports/{{name}}: mimeType {reply.mime_type()!r}"


def test_reports_list_only_findings(stocked):
    listed = stocked.read("triage://reports").document()
    want = {"count": 1, "reports": [{"name": "worker-pool-restarts-at-dawn", "title": "Worker pool restarts at dawn",
                                      "severity": "low", "created": "2026-01-15T10:00:00Z"}]}
    assert listed == want, (
        "triage://reports lists regular *.md files with the finding lines, and leaves out dot files, "
        f"symlinks, other names and markdown without those lines.\nexpected: {want}\ngot:      {listed}"
    )


@pytest.mark.parametrize("name", ["README", "linked", ".hidden", "notes", "missing-finding", "a.b"])
def test_reading_a_report_the_list_does_not_show(stocked, name):
    stocked.require_template("triage://reports/{name}")
    uri = f"triage://reports/{name}"
    not_found(stocked.read(uri), uri)


def test_a_uri_no_template_matches(server):
    server.require_template("triage://reports/{name}")
    not_found(server.read("triage://nothing/here"), "triage://nothing/here")


def test_scan_document(server):
    result = ok(server.call("summarize_logs", SMALL))
    uri = f"triage://scans/{result.get('scan_id')}"
    reply = server.read(uri)
    assert reply.document() == result, f"{uri} must hold the summarize_logs result of that scan"
    assert reply.mime_type() == "application/json", f"{uri}: mimeType {reply.mime_type()!r}"


def test_unknown_scan_document(server):
    server.require_template("triage://scans/{scan_id}")
    uri = "triage://scans/s_0123456789abcdef"
    not_found(server.read(uri), uri)


def test_expired_scan_document(short_server):
    uri = f"triage://scans/{short_server.scan(SMALL)}"
    assert short_server.read(uri).error is None, f"{uri} must be readable right after the scan"
    time.sleep(3)
    not_found(short_server.read(uri), uri)


def test_read_only_keeps_the_resources(tmp_path):
    running = Server("--read-only", root=S3_LOGS, reports=tmp_path / "reports")
    try:
        assert "triage://reports" in by_uri(running.resources(), "uri"), "--read-only removes only save_finding"
        assert running.read("triage://reports").document() == {"count": 0, "reports": []}
    finally:
        running.close()


def test_freshness_on_the_raw_frames(tmp_path):
    answers = raw_exchange(S3_LOGS, tmp_path / "reports", [
        ("resources/list", {}),
        ("resources/templates/list", {}),
        ("resources/read", {"uri": "triage://formats"}),
    ])
    for method, answer in zip(("resources/list", "resources/templates/list", "resources/read"), answers):
        assert "result" in answer, f"{method} failed on the raw connection: {answer.get('error')}"
        result = answer["result"]
        got = (result.get("ttlMs"), result.get("cacheScope"))
        assert got == (30000, "private"), (
            f"{method}: the result must carry ttlMs 30000 and cacheScope 'private' "
            f"(CONTRACT.md, Resources), got ttlMs={got[0]!r}, cacheScope={got[1]!r}"
        )
