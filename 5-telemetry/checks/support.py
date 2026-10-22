"""Start the server under test with telemetry on or off, talk to it, and read what it exported.

Nothing here imports the server. The command comes from LOG_TRIAGE_CMD (a JSON
array) or defaults to `uv run --project <repo>/solution log-triage`; the checks
add `--root`, `--reports`, `--log-level` and `--http` as separate arguments. Each
server gets its own OTLP receiver on a free loopback port and its own tiny
synthetic logs, not any investigation's evidence.
"""

from __future__ import annotations

import gzip
import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest
from google.protobuf import json_format

from receiver import Receiver, Record, attributes

CHECKS = Path(__file__).resolve().parent
REPO = CHECKS.parents[1]
SERVER = REPO / "solution"

PLAIN = "2040-01-01T00:00:00.000Z ERROR worker request 1 failed\n2040-01-01T00:00:01.000Z INFO worker ready\n"
WRITER = "p5-secret-writer"
VIEWER = "p5-secret-viewer"
TOKENS = f"{WRITER}=operator,{VIEWER}=observer:read-only"
MODERN = "2026-07-28"
SERVER_KIND = 2    # SPAN_KIND_SERVER
INTERNAL_KIND = 1  # SPAN_KIND_INTERNAL
STATUS_ERROR = 2   # STATUS_CODE_ERROR
START_TIMEOUT = 180  # the first `uv run` may have to install the server's environment
REPLY_TIMEOUT = 60
STOP_TIMEOUT = 6     # the contract's five-second flush, and a second to exit


def server_command() -> list[str]:
    raw = os.environ.get("LOG_TRIAGE_CMD")
    if not raw:
        return ["uv", "run", "--project", str(SERVER), "log-triage"]
    try:
        command = json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f'LOG_TRIAGE_CMD must be a JSON array of strings, like ["./bin/log-triage"]: {exc}')
    if not (isinstance(command, list) and command and all(isinstance(part, str) for part in command)):
        pytest.fail("LOG_TRIAGE_CMD must be a non-empty JSON array of strings")
    return command


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Server:
    """One server process, over stdio or HTTP, with its own receiver, log root and reports folder."""

    def __init__(self, folder: Path, transport: str, enabled: bool, extra: dict[str, str] | None):
        self.root = folder / "root"
        self.reports = folder / "reports"
        self.root.mkdir()
        self.reports.mkdir()
        (self.root / "alpha.log").write_text(PLAIN, encoding="utf-8")
        (self.root / "beta.log.gz").write_bytes(gzip.compress(PLAIN.encode("utf-8")))
        self.receiver = Receiver().start()
        env = {key: value for key, value in os.environ.items()
               if not key.startswith("OTEL_") and key not in ("LOG_TRIAGE_TOKENS", "VIRTUAL_ENV",
                                                            "FASTMCP_TELEMETRY_MODE")}
        if enabled:
            env["OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"] = self.receiver.url + "/v1/traces"
        env["OTEL_BSP_SCHEDULE_DELAY"] = "30000"
        env["LOG_TRIAGE_TOKENS"] = TOKENS
        env.update(extra or {})
        args = server_command() + ["--root", str(self.root), "--reports", str(self.reports), "--log-level", "debug"]
        self.url = ""
        if transport == "http":
            port = free_port()
            self.url = f"http://127.0.0.1:{port}/mcp"
            args += ["--http", f"127.0.0.1:{port}"]
        self.stderr_path = folder / "stderr.log"
        self._stdout = bytearray()
        self._lines: queue.Queue[bytes | None] = queue.Queue()
        self._next = 0
        self.stopped = False
        with open(self.stderr_path, "wb") as err:
            self.proc = subprocess.Popen(args, stdin=subprocess.PIPE if transport == "stdio" else subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=err, env=env)
        threading.Thread(target=self._read_stdout, daemon=True).start()
        if transport == "http":
            self._wait_for_http()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            self._stdout.extend(line)
            self._lines.put(line.rstrip(b"\n"))
        self._lines.put(None)

    def _wait_for_http(self) -> None:
        deadline = time.monotonic() + START_TIMEOUT
        while True:
            try:
                urllib.request.urlopen(self.url, timeout=2).close()
                return
            except urllib.error.HTTPError:
                return  # any HTTP answer means it listens
            except OSError:
                pass
            if self.proc.poll() is not None or time.monotonic() > deadline:
                pytest.fail(f"HTTP did not start: {self.stderr_text()}")
            time.sleep(0.05)

    def stderr_text(self) -> str:
        return self.stderr_path.read_text(encoding="utf-8", errors="replace") if self.stderr_path.exists() else ""

    def stdout_text(self) -> str:
        return bytes(self._stdout).decode("utf-8", errors="replace")

    def send(self, frame: dict) -> None:
        """One raw JSON-RPC frame on stdin."""
        self.proc.stdin.write(json.dumps(frame).encode("utf-8") + b"\n")
        self.proc.stdin.flush()

    def reply(self, what: str) -> dict:
        """The next JSON-RPC line on stdout."""
        try:
            raw = self._lines.get(timeout=REPLY_TIMEOUT)
        except queue.Empty:
            pytest.fail(f"no {what} response: {self.stderr_text()}")
        if raw is None:
            pytest.fail(f"server closed before replying to {what}: {self.stderr_text()}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            pytest.fail(f"stdout must be JSON-RPC: {raw!r} ({exc})")

    def rpc(self, method: str, params: dict | None = None, meta: dict | None = None, token: str = "") -> dict:
        self._next += 1
        p = dict(params or {})
        p["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": MODERN,
            "io.modelcontextprotocol/clientInfo": {"name": "p5-checks", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
            **(meta or {}),
        }
        message = {"jsonrpc": "2.0", "id": self._next, "method": method, "params": p}
        if not self.url:
            self.send(message)
            return self.reply(method)
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": MODERN, "Mcp-Method": method}
        if isinstance(p.get("name"), str):
            headers["Mcp-Name"] = p["name"]
        if isinstance(p.get("uri"), str):
            headers["Mcp-Name"] = p["uri"]
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(self.url, data=json.dumps(message).encode("utf-8"), headers=headers,
                                         method="POST")
        try:
            with urllib.request.urlopen(request, timeout=REPLY_TIMEOUT) as response:
                status, kind, raw = response.status, response.headers.get("Content-Type", ""), response.read()
        except urllib.error.HTTPError as exc:
            status, kind, raw = exc.code, exc.headers.get("Content-Type", ""), exc.read()
        text = raw.decode("utf-8", errors="replace")
        if status != 200:
            pytest.fail(f"HTTP {status}: {text}")
        if "event-stream" in kind:
            for line in text.splitlines():
                if line.startswith("data:"):
                    text = line[5:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            pytest.fail(f"the answer must be JSON-RPC: {text!r} ({exc})")

    def call(self, name: str, arguments: dict, meta: dict | None = None) -> dict:
        return self.rpc("tools/call", {"name": name, "arguments": arguments}, meta, WRITER)

    def stop(self, how: str) -> list[Record]:
        """Close stdin ("eof") or send SIGTERM ("signal"), wait for the exit, and return what arrived."""
        if self.stopped:
            return self.receiver.snapshot()
        self.stopped = True
        if how == "eof" and self.proc.stdin is not None:
            self.proc.stdin.close()
        else:
            self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            pytest.fail("server did not flush and stop within shutdown bound")
        if self.url and self.stdout_text():
            pytest.fail(f"HTTP stdout must be empty: {self.stdout_text()!r}")
        return self.receiver.snapshot()

    def close(self) -> None:
        if not self.stopped:
            self.stopped = True
            if self.proc.poll() is None:
                self.proc.send_signal(signal.SIGTERM)
                try:
                    self.proc.wait(timeout=STOP_TIMEOUT)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
                    self.proc.wait()
        self.receiver.close()


def find(rows: list[Record], name: str) -> Record:
    for row in rows:
        if row.span.name == name:
            return row
    pytest.fail(f"missing {name!r} span: implement this task's instrumentation ({len(rows)} exported spans)")


def attrs(row: Record) -> dict[str, Any]:
    return attributes(row.span.attributes)


def dumped(row: Record) -> str:
    """The whole exported record as text: span, attributes, events, status and resource."""
    return json_format.MessageToJson(row.span) + json.dumps(row.resource)


def structured(reply: dict) -> dict:
    value = (reply.get("result") or {}).get("structuredContent")
    if not isinstance(value, dict):
        pytest.fail(f"successful structured result required: {reply}")
    return value


def integer(value: Any) -> int:
    assert isinstance(value, int) and not isinstance(value, bool), f"expected integer span attribute, got {value!r}"
    return value
