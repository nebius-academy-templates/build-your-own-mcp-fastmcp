"""Start the server under test over HTTP (and stdio where a check needs it) and talk to it.

Nothing here imports the server. The command comes from LOG_TRIAGE_CMD (a JSON
array) or defaults to `uv run --project <repo>/solution log-triage`; the checks
add `--root`, `--reports`, `--http` and any other flags as separate arguments,
and set LOG_TRIAGE_TOKENS themselves.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.client.transports import StdioTransport
from mcp.shared.exceptions import MCPError

CHECKS = Path(__file__).resolve().parent
REPO = CHECKS.parents[1]
S3_LOGS = REPO / "s3_logs"
SERVER = REPO / "solution"
EXPECTED = json.loads((CHECKS / "expected.json").read_text(encoding="utf-8"))
CALLS = {call["id"]: call for call in EXPECTED["calls"]}
TOKENS = EXPECTED["tokens"]
CALLERS = EXPECTED["callers"]
OWNER, OWNER_2 = CALLERS["owner"]
OTHER = CALLERS["other"]
VIEWER = CALLERS["read_only"]
UNKNOWN = CALLERS["unknown"]
ORIGINS = EXPECTED["origins"]
PROMPT = EXPECTED["prompt"]
TOOLS = EXPECTED["tools"]

START_TIMEOUT = 180  # the first `uv run` may have to install the server's environment
CALL_TIMEOUT = 120
SCAN_ID_RE = re.compile(r"^s_[0-9a-f]{16}$")
NOT_FOUND = -32602
MODERN = "2026-07-28"
LEGACY = "2025-11-25"
NAMED_METHODS = {"tools/call", "prompts/get", "resources/read"}

P1_INSTRUCTIONS = (
    "Log Triage reads log files under one folder. Start with list_logs to see what is there. "
    "Use summarize_logs on a file or folder, with since and until when you know the time, to get "
    "counts and message groups instead of raw lines. Use search_logs to find the lines that match a "
    "pattern. Record a conclusion with save_finding and cite a file and line for every piece of "
    "evidence. All times are UTC."
)
P3_SENTENCE = (
    "Use timeline with a scan_id to see how often a pattern occurs over time, and how a number in "
    "those lines moves."
)
P4_SENTENCE = "For a guided investigation, use the triage prompt."
TOKENS_MISSING = "LOG_TRIAGE_TOKENS is required with --http"
E13 = "save_finding is not available to this caller."


def p2_sentence(lifetime: str) -> str:
    return (
        f"summarize_logs returns a scan_id that works for {lifetime}; pass it to group_lines to read "
        "one group's lines without scanning again. Use read_lines for the lines around one line. "
        "Saved findings are listed at triage://reports."
    )


def e6(scan_id: str) -> str:
    return f'scan "{scan_id}" is unknown or has expired. Call summarize_logs again for a new scan_id.'


# ------------------------------------------------------------------ command and values


def server_command() -> list[str]:
    raw = os.environ.get("LOG_TRIAGE_CMD")
    if not raw:
        return ["uv", "run", "--project", str(SERVER), "log-triage"]
    try:
        cmd = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f'LOG_TRIAGE_CMD must be a JSON array of strings, like ["./bin/log-triage"]: {exc}')
    if not (isinstance(cmd, list) and cmd and all(isinstance(part, str) for part in cmd)):
        pytest.fail("LOG_TRIAGE_CMD must be a non-empty JSON array of strings")
    return cmd


def child_env(tokens: str | None) -> dict[str, str]:
    """The checks' environment without the virtualenv, with LOG_TRIAGE_TOKENS set or removed."""
    env = {key: value for key, value in os.environ.items()
           if key not in ("VIRTUAL_ENV", "LOG_TRIAGE_TOKENS")}
    if tokens is not None:
        env["LOG_TRIAGE_TOKENS"] = tokens
    return env


def fill(value: Any, places: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, text in places.items():
            value = value.replace("{" + key + "}", text)
        return value
    if isinstance(value, dict):
        return {key: fill(item, places) for key, item in value.items()}
    if isinstance(value, list):
        return [fill(item, places) for item in value]
    return value


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def corpus_names() -> set[str]:
    """Host folder names under s3_logs and the dates in its file names."""
    names = set()
    for group in S3_LOGS.iterdir():
        if group.is_dir():
            names.update(host.name for host in group.iterdir() if host.is_dir())
    for path in S3_LOGS.rglob("*"):
        names.update(re.findall(r"\d{4}-\d{2}-\d{2}", path.name))
    return names


# ------------------------------------------------------------------ replies


@dataclass
class Reply:
    tool: str
    arguments: dict
    error: MCPError | None = None
    is_error: bool = False
    structured: Any = None
    texts: list[str] = field(default_factory=list)
    other_blocks: int = 0

    def label(self) -> str:
        return f"{self.tool}({json.dumps(self.arguments)[:160]})"

    def summary(self) -> str:
        if self.error is not None:
            return f"JSON-RPC error {self.error.error.code}: {self.error.error.message[:300]}"
        text = " | ".join(t[:300] for t in self.texts)
        return f"isError={self.is_error}, text: {text}"


def ok(reply: Reply) -> dict:
    """A successful call: no error, structuredContent, and one text block with the same JSON."""
    where = reply.label()
    assert reply.error is None, f"{where} failed: {reply.summary()}"
    assert not reply.is_error, f"{where} returned a tool error: {reply.summary()}"
    assert isinstance(reply.structured, dict), f"{where} returned no structuredContent"
    assert len(reply.texts) == 1 and reply.other_blocks == 0, (
        f"{where} returned {len(reply.texts)} text blocks and {reply.other_blocks} other blocks; "
        f"expected one text block holding the same object as JSON"
    )
    assert json.loads(reply.texts[0]) == reply.structured, (
        f"{where}: the text block's JSON differs from structuredContent"
    )
    return reply.structured


def tool_error(reply: Reply, text: str) -> None:
    """Refused by the tool itself with exactly the contract's text."""
    assert reply.error is None, (
        f"{reply.label()} must come back as a tool error (a result with isError: true), got {reply.summary()}"
    )
    assert reply.is_error, f"{reply.label()} was accepted; it must answer: {text}"
    assert reply.structured is None, f"{reply.label()} is an error but carries structuredContent"
    got = " ".join(reply.texts)
    assert got == text, (
        f"{reply.label()}: the error text must be exactly the contract's (CONTRACT.md, Errors).\n"
        f"expected: {text!r}\ngot:      {got!r}"
    )


def same(actual: Any, expected: Any, where: str) -> None:
    """Equal values; a dict may hold keys the facts don't name."""
    if isinstance(expected, dict):
        assert isinstance(actual, dict), f"{where}: expected an object, got {actual!r:.200}"
        missing = [key for key in expected if key not in actual]
        assert not missing, f"{where}: missing field(s) {missing}"
        for key, value in expected.items():
            same(actual[key], value, f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list), f"{where}: expected a list, got {actual!r:.200}"
        for index, (got, want) in enumerate(zip(actual, expected)):
            same(got, want, f"{where}[{index}]")
        assert len(actual) == len(expected), f"{where}: expected {len(expected)} items, got {len(actual)}"
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual == expected, (
            f"{where}: expected the number {expected!r}, got {actual!r:.200}"
        )
    else:
        assert type(actual) is type(expected) and actual == expected, (
            f"{where}: expected {expected!r:.200}, got {actual!r:.200}"
        )


@dataclass
class Raw:
    """One HTTP exchange: status, headers (lower-case names) and the JSON-RPC message, if any."""
    label: str
    status: int
    headers: dict[str, str]
    body: str
    message: dict | None

    def describe(self) -> str:
        return f"{self.label}: HTTP {self.status}, body {self.body[:300]!r}"

    def result(self) -> dict:
        assert self.status == 200, f"{self.describe()}; expected HTTP 200"
        assert self.message is not None, f"{self.describe()}; expected one JSON-RPC answer"
        assert "error" not in self.message, f"{self.describe()}; expected a result"
        return self.message["result"]


def parse_message(content_type: str, body: str) -> dict | None:
    """The JSON-RPC answer from a JSON body or from the last data line of an event stream."""
    text = body.strip()
    if "text/event-stream" in content_type:
        datas = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        text = datas[-1] if datas else ""
    try:
        message = json.loads(text)
    except json.JSONDecodeError:
        return None
    return message if isinstance(message, dict) and message.get("jsonrpc") == "2.0" else None


def refused(raw: Raw, why: str) -> None:
    """An SDK refusal, judged by its JSON-RPC answer and never by the HTTP status."""
    assert raw.message is not None, f"{raw.describe()}; {why}, and the answer must still be JSON-RPC"
    if "error" in raw.message:
        return
    result = raw.message.get("result") or {}
    assert result.get("isError") is True and result.get("structuredContent") is None, (
        f"{raw.describe()}; {why}, so it must be refused (a JSON-RPC error, or isError without structuredContent)"
    )


def rpc_error(raw: Raw, why: str) -> None:
    """A JSON-RPC error answer, whatever its code and HTTP status: no result."""
    assert raw.message is not None, f"{raw.describe()}; {why}, and the answer must still be JSON-RPC"
    error = raw.message.get("error")
    assert isinstance(error, dict) and isinstance(error.get("code"), int), (
        f"{raw.describe()}; {why}, so the answer must be a JSON-RPC error (CONTRACT.md, section 5), not a result"
    )


def bearer_challenge(raw: Raw) -> None:
    assert raw.status == 401, f"{raw.describe()}; a request without a known token must answer 401. Task 1."
    challenge = raw.headers.get("www-authenticate", "")
    assert challenge.split(" ", 1)[0].lower() == "bearer", (
        f"{raw.label}: a 401 must carry a WWW-Authenticate header whose scheme is Bearer, got {challenge!r}"
    )


# ------------------------------------------------------------------ the server over HTTP


class HttpServer:
    """One server process with --http on a free local port."""

    def __init__(self, *flags: str, root: Path = S3_LOGS, reports: Path | None = None,
                 tokens: str | None = TOKENS):
        self.root = Path(root).resolve()
        self.reports = reports
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}/mcp"
        args = ["--root", str(root)]
        if reports is not None:
            args += ["--reports", str(reports)]
        self.command = server_command() + args + ["--http", f"127.0.0.1:{self.port}"] + list(flags)
        self.tokens = tokens
        self._dir = Path(tempfile.mkdtemp(prefix="log-triage-checks-"))
        self.stdout_path = self._dir / "stdout.log"
        self.stderr_path = self._dir / "stderr.log"
        self.proc: subprocess.Popen | None = None
        self._failure: str | None = None

    def start(self) -> "HttpServer":
        if self.proc is not None:
            return self
        with open(self.stdout_path, "wb") as out, open(self.stderr_path, "wb") as err:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                         env=child_env(self.tokens))
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self._failure = f"the server exited with code {self.proc.returncode}"
                return self
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=1):
                    return self
            except OSError:
                time.sleep(0.2)
        self._failure = f"nothing listened on 127.0.0.1:{self.port} within {START_TIMEOUT} s"
        return self

    def exit_code(self) -> int | None:
        """For a server that should refuse to start: its exit code, or None if it kept running."""
        self.start()
        return self.proc.poll()

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)
        shutil.rmtree(self._dir, ignore_errors=True)

    def require(self) -> None:
        self.start()
        if self._failure is not None:
            pytest.fail(
                "The server did not start over HTTP, so this check can't run.\n"
                f"Command: {shlex.join(self.command)}\n"
                f"Error: {self._failure}\n"
                f"Last lines on the server's stderr:\n{self.stderr_tail()}\n"
                "CONTRACT.md sections 1 and 7 require --http; the server must start with these flags and "
                "LOG_TRIAGE_TOKENS set. To test another build, set LOG_TRIAGE_CMD to its command as a JSON array.",
                pytrace=False,
            )

    def stdout_bytes(self) -> bytes:
        return self.stdout_path.read_bytes() if self.stdout_path.exists() else b""

    def stderr_text(self) -> str:
        return self.stderr_path.read_text(encoding="utf-8", errors="replace") if self.stderr_path.exists() else ""

    def stderr_tail(self, lines: int = 15) -> str:
        return "\n".join(self.stderr_text().splitlines()[-lines:]) or "(nothing)"

    # raw HTTP

    def post(self, body: dict, token: str | None = OWNER, origin: str | None = None,
             headers: dict[str, str] | None = None, label: str = "") -> Raw:
        self.require()
        sent = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token is not None:
            sent["Authorization"] = f"Bearer {token}"
        if origin is not None:
            sent["Origin"] = origin
        sent.update(headers or {})
        request = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), headers=sent,
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=CALL_TIMEOUT) as response:
                status, got, text = response.status, dict(response.headers), response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status, got, text = exc.code, dict(exc.headers), exc.read().decode("utf-8", "replace")
        got = {key.lower(): value for key, value in got.items()}
        return Raw(label or body.get("method", "?"), status, got, text,
                   parse_message(got.get("content-type", ""), text))

    def rpc(self, method: str, params: dict | None = None, token: str | None = OWNER,
            origin: str | None = None, headers: dict[str, str] | None = None) -> Raw:
        """One request in protocol revision 2026-07-28, with the headers it needs on HTTP."""
        params = dict(params or {})
        sent = {"MCP-Protocol-Version": MODERN, "Mcp-Method": method}
        if method in NAMED_METHODS:
            sent["Mcp-Name"] = params.get("name") or params.get("uri") or ""
        sent.update(headers or {})
        meta = {
            "io.modelcontextprotocol/protocolVersion": MODERN,
            "io.modelcontextprotocol/clientInfo": {"name": "log-triage-checks", "version": "4"},
            "io.modelcontextprotocol/clientCapabilities": {},
        }
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": meta}}
        label = f"{method} {json.dumps(params)[:120]} (token {token!r}, Origin {origin!r})"
        return self.post(body, token=token, origin=origin, headers=sent, label=label)

    # MCP through FastMCP's client, one connection per call

    def _with_client(self, token: str | None, work):
        self.require()

        async def go():
            async with Client(self.url, auth=BearerAuth(token) if token else None,
                              timeout=CALL_TIMEOUT) as client:
                return await work(client)

        return asyncio.run(go())

    def tool_names(self, token: str | None = OWNER) -> list[str]:
        return [tool.name for tool in self._with_client(token, lambda client: client.list_tools())]

    def call(self, name: str, arguments: dict, token: str | None = OWNER) -> Reply:
        async def go(client: Client):
            try:
                return await client.call_tool_mcp(name, arguments, timeout=CALL_TIMEOUT)
            except MCPError as exc:
                return exc

        result = self._with_client(token, go)
        reply = Reply(tool=name, arguments=arguments)
        if isinstance(result, MCPError):
            reply.error = result
            return reply
        reply.is_error = bool(result.is_error)
        reply.structured = result.structured_content
        for block in result.content:
            if getattr(block, "type", None) == "text":
                reply.texts.append(block.text)
            else:
                reply.other_blocks += 1
        return reply

    def scan(self, arguments: dict, token: str = OWNER) -> str:
        result = ok(self.call("summarize_logs", arguments, token))
        scan_id = result.get("scan_id")
        assert isinstance(scan_id, str) and SCAN_ID_RE.match(scan_id), (
            f"summarize_logs must return a scan_id like s_ and 16 lowercase hex characters, got {scan_id!r}"
        )
        return scan_id

    def read(self, uri: str, token: str = OWNER) -> tuple[MCPError | None, list[dict]]:
        async def go(client: Client):
            try:
                return await client.read_resource_mcp(uri)
            except MCPError as exc:
                return exc

        result = self._with_client(token, go)
        if isinstance(result, MCPError):
            return result, []
        dumped = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        return None, dumped.get("contents") or []

    def prompts(self, token: str = OWNER) -> list[dict]:
        listed = self._with_client(token, lambda client: client.list_prompts())
        return [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in listed]

    def get_prompt(self, arguments: dict, token: str = OWNER) -> dict:
        async def go(client: Client):
            return await client.get_prompt(PROMPT["name"], arguments)

        return self._with_client(token, go).model_dump(mode="json", by_alias=True, exclude_none=True)


def run_call(server: HttpServer, call_id: str, scan_token: str, call_token: str) -> tuple[Reply, dict]:
    """One expected.json call: its scan made with scan_token, the call made with call_token."""
    call = CALLS[call_id]
    places = {"root": str(server.root)}
    args = dict(call["args"])
    if "scan" in call:
        places["scan_id"] = server.scan(call["scan"], scan_token)
        args = {"scan_id": places["scan_id"], **args}
        if "group_id" in call:
            args["group_id"] = call["group_id"]
    return server.call(call["tool"], args, call_token), places


def check_answer(server: HttpServer, call_id: str, scan_token: str = OWNER, call_token: str = OWNER) -> dict:
    call = CALLS[call_id]
    reply, places = run_call(server, call_id, scan_token, call_token)
    result = ok(reply)
    same(result, fill(call["result"], places), f"{call['tool']} {call_id}")
    return result


# ------------------------------------------------------------------ the server over stdio


def stdio_session(work, *flags: str):
    """Start the server over stdio, run work(client) and stop it."""
    command = server_command() + ["--root", str(S3_LOGS), *flags]

    async def go():
        transport = StdioTransport(command=command[0], args=command[1:], keep_alive=False)
        async with Client(transport, init_timeout=START_TIMEOUT, timeout=CALL_TIMEOUT) as client:
            return await work(client)

    try:
        return asyncio.run(go())
    except Exception as exc:  # a server that never starts ends up here
        pytest.fail(f"The server did not start over stdio: {type(exc).__name__}: {exc}\n"
                    f"Command: {shlex.join(command)}", pytrace=False)
