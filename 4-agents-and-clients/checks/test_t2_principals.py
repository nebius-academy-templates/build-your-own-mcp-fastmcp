"""Task 2: callers from tokens: scan ownership, the read-only caller and E13, --read-only over tokens."""

from __future__ import annotations

import json

from support import (
    CALLS, E13, NOT_FOUND, OTHER, OWNER, OWNER_2, TOOLS, VIEWER, HttpServer, check_answer, e6, ok, refused,
    tool_error,
)

TASK = "Task 2 makes the caller come from the token."
WINDOW = CALLS["group-lines-app-window"]["scan"]
GROUP = CALLS["group-lines-app-window"]["group_id"]
EVIDENCE = [{"file": "pods/provisioner-2/archive/app-2026-08-30.log.gz", "line": 1, "note": "first line"}]


def finding(title: str) -> dict:
    return {"title": title, "severity": "low", "summary": "A finding the checks save over HTTP.",
            "evidence": EVIDENCE}


def test_a_scan_works_from_a_second_token_of_its_owner(server):
    check_answer(server, "group-lines-app-window", scan_token=OWNER, call_token=OWNER_2)
    check_answer(server, "timeline-app-window", scan_token=OWNER, call_token=OWNER_2)


def test_the_scan_resource_works_for_its_owner(server):
    scan_id = server.scan(WINDOW, OWNER)
    error, contents = server.read(f"triage://scans/{scan_id}", OWNER_2)
    assert error is None, (
        f"reading triage://scans/{scan_id} with another token of the same caller failed: "
        f"{error.error.code} {error.error.message[:200]}. {TASK}"
    )
    document = json.loads(contents[0]["text"])
    assert document.get("scan_id") == scan_id, f"triage://scans/{scan_id} must hold that scan's summary"


def test_another_caller_gets_e6(server):
    scan_id = server.scan(WINDOW, OWNER)
    tool_error(server.call("group_lines", {"scan_id": scan_id, "group_id": GROUP}, OTHER), e6(scan_id))
    tool_error(server.call("timeline", {"scan_id": scan_id}, OTHER), e6(scan_id))
    error, _ = server.read(f"triage://scans/{scan_id}", OTHER)
    assert error is not None and error.error.code == NOT_FOUND, (
        f"another caller reading triage://scans/{scan_id} must get the resource-not-found error "
        f"({NOT_FOUND}); got {'a result' if error is None else error.error.code}. {TASK}"
    )


def test_the_writer_sees_every_tool(server):
    names = server.tool_names(OWNER)
    missing = sorted(set(TOOLS["writer"]) - set(names))
    assert not missing, f"a caller with a writing token must see {missing} in tools/list"


def test_the_read_only_caller_does_not_see_save_finding(server):
    names = server.tool_names(VIEWER)
    assert "save_finding" not in names, (
        f"a read-only caller must not see save_finding in tools/list (CONTRACT.md, section 7); got {names}. {TASK}"
    )
    missing = sorted(set(TOOLS["read_only"]) - set(names))
    assert not missing, f"a read-only caller must still see {missing}"


def test_the_read_only_caller_gets_e13(server):
    before = sorted(p.name for p in server.reports.iterdir())
    tool_error(server.call("save_finding", finding("Read-only caller tries to write"), VIEWER), E13)
    after = sorted(p.name for p in server.reports.iterdir())
    assert after == before, f"a refused save_finding must write nothing; new files: {sorted(set(after) - set(before))}"


def test_the_read_only_caller_scans_for_itself(server):
    scan_id = server.scan(WINDOW, VIEWER)
    ok(server.call("group_lines", {"scan_id": scan_id, "group_id": GROUP}, VIEWER))
    tool_error(server.call("group_lines", {"scan_id": scan_id, "group_id": GROUP}, OWNER), e6(scan_id))


def test_tools_list_is_private(server):
    for token in (OWNER, VIEWER):
        result = server.rpc("tools/list", token=token).result()
        assert result.get("cacheScope") == "private", (
            f"tools/list must carry cacheScope \"private\", because the list depends on the caller "
            f"(CONTRACT.md, section 4); got {result.get('cacheScope')!r} for token {token}"
        )


def test_scan_caps_are_per_caller(server):
    kept = server.scan(WINDOW, OWNER)
    first = server.scan(WINDOW, OTHER)
    for _ in range(20):
        server.scan(WINDOW, OTHER)
    tool_error(server.call("group_lines", {"scan_id": first, "group_id": GROUP}, OTHER), e6(first))
    ok(server.call("group_lines", {"scan_id": kept, "group_id": GROUP}, OWNER))


def test_a_finding_saved_over_http_is_listed(server):
    saved = ok(server.call("save_finding", finding("Saved over HTTP by the checks"), OWNER))
    error, contents = server.read("triage://reports", OWNER)
    assert error is None, f"reading triage://reports failed: {error.error.message[:200] if error else ''}"
    names = [report.get("name") for report in json.loads(contents[0]["text"]).get("reports", [])]
    assert saved["name"] in names, f"triage://reports must list the finding saved over HTTP; got {names}"


def test_read_only_flag_wins_over_tokens(tmp_path):
    running = HttpServer("--read-only", reports=tmp_path)
    try:
        names = running.tool_names(OWNER)
        assert "save_finding" not in names, (
            f"with --read-only no caller sees save_finding, whatever its token; got {names}"
        )
        raw = running.rpc("tools/call", {"name": "save_finding", "arguments": finding("Not registered")})
        refused(raw, "save_finding isn't registered with --read-only")
        if raw.message and "result" in raw.message:
            texts = [block.get("text") for block in raw.message["result"].get("content") or []]
            assert E13 not in texts, (
                "with --read-only, a call to save_finding is the SDK's unknown-tool refusal, not E13 "
                "(CONTRACT.md, section 7)"
            )
        assert list(tmp_path.iterdir()) == [], "with --read-only nothing may be written"
    finally:
        running.close()
