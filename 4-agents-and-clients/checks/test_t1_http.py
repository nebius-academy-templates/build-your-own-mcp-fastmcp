"""Task 1: --http, the tokens, 401, the Origin check, both protocol revisions, an empty stdout."""

from __future__ import annotations

import pytest

from support import (
    LEGACY, ORIGINS, OWNER, TOKENS_MISSING, TOOLS, UNKNOWN, HttpServer, bearer_challenge, check_answer,
    fill,
)

TASK = "Task 1 adds --http with bearer tokens and the Origin check."


def test_http_without_tokens_exits_2(tmp_path):
    running = HttpServer(reports=tmp_path, tokens=None)
    try:
        code = running.exit_code()
        assert code is not None, (
            "with --http and no LOG_TRIAGE_TOKENS the server must exit, but it started. " + TASK
        )
        assert code == 2, f"with --http and no LOG_TRIAGE_TOKENS the exit code must be 2, got {code}"
        lines = running.stderr_text().splitlines()
        assert TOKENS_MISSING in lines, (
            f"stderr must hold the line {TOKENS_MISSING!r} (CONTRACT.md, section 1); last lines:\n"
            f"{running.stderr_tail()}"
        )
    finally:
        running.close()


def test_tools_list_with_a_token(server):
    tools = server.rpc("tools/list").result().get("tools") or []
    names = {tool.get("name") for tool in tools}
    missing = sorted(set(TOOLS["writer"]) - names)
    assert not missing, f"tools/list over HTTP with a known token lacks {missing}. {TASK}"


def test_a_tool_call_with_a_token(server):
    check_answer(server, "summary-app-window")


@pytest.mark.parametrize("header", [None, "Basic YWJjOmRlZg==", "Bearer", f"Bearer {UNKNOWN}"],
                         ids=["no-header", "basic", "empty-bearer", "unknown-token"])
def test_no_known_token_gets_401(server, header):
    headers = {"Authorization": header} if header else {}
    raw = server.rpc("tools/list", token=None, headers=headers)
    bearer_challenge(raw)


@pytest.mark.parametrize("token", [OWNER, None], ids=["with-token", "without-token"])
@pytest.mark.parametrize("origin", ORIGINS["forbidden"])
def test_a_foreign_origin_gets_403(server, origin, token):
    origin = fill(origin, {"port": str(server.port)})
    raw = server.rpc("tools/list", token=token, origin=origin)
    assert raw.status == 403, (
        f"{raw.describe()}; an Origin other than http://localhost[:port] or http://127.0.0.1[:port] must answer "
        "403, before the token is looked at (CONTRACT.md, section 7). " + TASK
    )


@pytest.mark.parametrize("origin", ORIGINS["allowed"])
def test_a_local_origin_passes(server, origin):
    origin = fill(origin, {"port": str(server.port)})
    server.rpc("tools/list", origin=origin).result()


def test_the_older_protocol_revision(server):
    hello = server.post({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": LEGACY, "capabilities": {},
                   "clientInfo": {"name": "log-triage-checks", "version": "4"}},
    }, label=f"initialize {LEGACY}")
    assert hello.result().get("protocolVersion"), f"{hello.describe()}; initialize must answer a protocolVersion"
    listed = server.post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                         headers={"MCP-Protocol-Version": LEGACY}, label=f"tools/list {LEGACY}, no session id")
    names = {tool.get("name") for tool in listed.result().get("tools") or []}
    assert "list_logs" in names, (
        f"{listed.describe()}; after an initialize, a tools/list without a session id must be answered "
        "(stateless HTTP, CONTRACT.md section 7)"
    )


def test_stdout_stays_empty(server):
    server.rpc("tools/list").result()
    server.rpc("tools/list", token=None)
    server.call("list_logs", {"path": "pods"})
    assert server.stdout_bytes() == b"", (
        "with --http nothing may reach stdout, the HTTP server's access lines included; stdout holds:\n"
        f"{server.stdout_bytes()[:300]!r}"
    )


def test_one_tool_line_per_call_over_http(tmp_path):
    running = HttpServer("--log-level", "debug", reports=tmp_path)
    try:
        running.call("list_logs", {"path": "pods"})
        running.call("read_lines", {"path": "pods/provisioner-2/archive/app-2026-08-30.log.gz", "line": 1})
        running.call("list_logs", {"path": "pods", "no_such_argument": 1})
        lines = [line for line in running.stderr_text().splitlines() if "tool=" in line]
        assert len(lines) == 3, (
            f"three tools/call requests over HTTP at --log-level debug must write three lines containing tool=, "
            f"one of them for the call the schema refused (CONTRACT.md, section 1); got {len(lines)}:\n"
            + "\n".join(lines[:10])
        )
        assert running.stdout_bytes() == b"", "with --http nothing may reach stdout, logging included"
    finally:
        running.close()
