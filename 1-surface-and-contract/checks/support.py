"""Start the server under test and talk to it over MCP.

Nothing here imports the server. The command comes from LOG_TRIAGE_CMD (a JSON
array) or defaults to `uv run --project <repo>/solution log-triage`; the checks
add `--root`, `--reports` and any other flags as separate arguments.
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import re
import shlex
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from mcp.shared.exceptions import MCPError

CHECKS = Path(__file__).resolve().parent
REPO = CHECKS.parents[1]
S3_LOGS = REPO / "s3_logs"
SERVER = REPO / "solution"
EXPECTED = json.loads((CHECKS / "expected.json").read_text(encoding="utf-8"))
CALLS = {call["id"]: call for call in EXPECTED["calls"]}

START_TIMEOUT = 180  # the first `uv run` may have to install the server's environment
CALL_TIMEOUT = 120
TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


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


def calls_for(tool: str) -> list[str]:
    return [call_id for call_id, call in CALLS.items() if call["tool"] == tool]


def fill_root(value: Any, root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{root}", str(root))
    if isinstance(value, dict):
        return {key: fill_root(item, root) for key, item in value.items()}
    return value


def build_tree(dest: Path) -> Path:
    """The temporary log root described in expected.json: copies, gunzipped copies, text."""
    for entry in EXPECTED["tree"]:
        target = dest / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if "copy" in entry:
            shutil.copyfile(S3_LOGS / entry["copy"], target)
        elif "gunzip" in entry:
            target.write_bytes(gzip.decompress((S3_LOGS / entry["gunzip"]).read_bytes()))
        else:
            target.write_bytes(("\n".join(entry["text"]) + "\n").encode("utf-8"))
    return dest


def raw_lines(path: Path) -> list[str]:
    data = path.read_bytes()
    if path.name.endswith(".gz"):
        data = gzip.decompress(data)
    return data.decode("utf-8", "replace").splitlines()


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
    assert isinstance(reply.structured, dict), (
        f"{where} returned no structuredContent. Give the tool a return type the SDK turns into "
        f"an output schema (see CONTRACT.md, Tools)."
    )
    assert len(reply.texts) == 1 and reply.other_blocks == 0, (
        f"{where} returned {len(reply.texts)} text blocks and {reply.other_blocks} other blocks; "
        f"expected one text block holding the same object as JSON"
    )
    try:
        parsed = json.loads(reply.texts[0])
    except json.JSONDecodeError:
        pytest.fail(f"{where}: the text block is not JSON: {reply.texts[0][:200]!r}")
    assert parsed == reply.structured, f"{where}: the text block's JSON differs from structuredContent"
    return reply.structured


def refused_by_schema(reply: Reply, why: str) -> None:
    """Refused before the tool runs: a JSON-RPC error, or isError with no structuredContent."""
    if reply.error is not None:
        return
    assert reply.is_error, f"{reply.label()} was accepted, but {why}; it must be refused before the tool runs"
    assert reply.structured is None, f"{reply.label()} is an error but carries structuredContent"


def tool_error(reply: Reply, why: str) -> None:
    """Refused by the tool itself: a result with isError true."""
    assert reply.error is None, (
        f"{reply.label()} must come back as a tool error (a result with isError: true), "
        f"got {reply.summary()}"
    )
    assert reply.is_error, f"{reply.label()} was accepted, but {why}"
    assert reply.structured is None, f"{reply.label()} is an error but carries structuredContent"


def same(actual: Any, expected: Any, where: str) -> None:
    """Equal values; a dict may hold keys the facts don't name (later practices add some)."""
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
        assert len(actual) == len(expected), (
            f"{where}: expected {len(expected)} items, got {len(actual)}"
        )
    else:
        assert type(actual) is type(expected) and actual == expected, (
            f"{where}: expected {expected!r:.200}, got {actual!r:.200}"
        )


def check_answer(server: "Server", call_id: str) -> dict:
    call = CALLS[call_id]
    args = fill_root(call["args"], server.root)
    result = ok(server.call(call["tool"], args))
    tool = server.tool(call["tool"])
    try:
        jsonschema.validate(result, tool.get("outputSchema") or {})
    except jsonschema.ValidationError as exc:
        pytest.fail(f"{call['tool']} {call_id}: structuredContent does not match the outputSchema: {exc.message}")
    same(result, call["result"], f"{call['tool']} {call_id}")
    return result


# ------------------------------------------------------------------ schemas


def resolve(schema: dict, root: dict) -> dict:
    while isinstance(schema, dict) and "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"unsupported $ref {ref}"
        node: Any = root
        for part in ref[2:].split("/"):
            node = node[part]
        schema = node
    return schema


def branches(schema: dict, root: dict) -> list[dict]:
    schema = resolve(schema, root)
    for key in ("anyOf", "oneOf"):
        if key in schema:
            out = []
            for branch in schema[key]:
                out.extend(branches(branch, root))
            return out
    return [schema]


def types_of(schema: dict, root: dict) -> set[str]:
    found: set[str] = set()
    for branch in branches(schema, root):
        kind = branch.get("type")
        if isinstance(kind, list):
            found.update(kind)
        elif kind is not None:
            found.add(kind)
    return found


def value_branch(schema: dict, root: dict) -> dict:
    """The branch that isn't null, for bounds on a nullable parameter."""
    real = [b for b in branches(schema, root) if b.get("type") not in ("null", ["null"])]
    assert len(real) == 1, f"expected one non-null branch in {schema}"
    return real[0]


def input_property(tool: dict, name: str) -> dict:
    schema = tool["inputSchema"]
    props = schema.get("properties") or {}
    assert name in props, f"{tool['name']}: the input schema has no parameter {name!r}"
    return props[name]


def check_plain(tool: dict, name: str, kind: str, **bounds: Any) -> None:
    root = tool["inputSchema"]
    prop = input_property(tool, name)
    kinds = types_of(prop, root)
    assert kinds == {kind}, (
        f"{tool['name']}.{name}: type must be exactly {kind!r}, got {sorted(kinds)} "
        f"(a pointer, a slice or an Optional makes it nullable)"
    )
    check_bounds(tool, name, value_branch(prop, root), bounds)


def check_nullable_string(tool: dict, name: str, **bounds: Any) -> None:
    root = tool["inputSchema"]
    prop = input_property(tool, name)
    kinds = types_of(prop, root)
    assert kinds == {"string", "null"}, f"{tool['name']}.{name}: type must be string or null, got {sorted(kinds)}"
    assert resolve(prop, root).get("default", None) is None, f"{tool['name']}.{name}: the default must be null"
    check_bounds(tool, name, value_branch(prop, root), bounds)


def same_json_value(got: Any, want: Any) -> bool:
    if isinstance(want, bool) or isinstance(got, bool):
        return got is want
    if isinstance(want, (int, float)):
        return isinstance(got, (int, float)) and got == want
    return got == want


def check_bounds(tool: dict, name: str, schema: dict, bounds: dict) -> None:
    for key, want in bounds.items():
        if key == "default":
            prop = resolve(input_property(tool, name), tool["inputSchema"])
            got = prop.get("default", schema.get("default"))
        else:
            got = schema.get(key)
        assert same_json_value(got, want), f"{tool['name']}.{name}: {key} must be {want!r}, got {got!r}"


def check_enum(tool: dict, name: str, values: list[str], default: str | None = None) -> None:
    root = tool["inputSchema"]
    prop = input_property(tool, name)
    kinds = types_of(prop, root)
    assert kinds == {"string"}, f"{tool['name']}.{name}: type must be exactly 'string', got {sorted(kinds)}"
    got = value_branch(prop, root).get("enum")
    assert got is not None and sorted(got) == sorted(values), (
        f"{tool['name']}.{name}: enum must be {values}, got {got}"
    )
    if default is not None:
        check_bounds(tool, name, value_branch(prop, root), {"default": default})


def required_of(tool: dict) -> set[str]:
    return set(tool["inputSchema"].get("required") or [])


def output_fields(tool: dict, *path: str) -> set[str]:
    """Property names of the output schema, or of a nested object or list item under it."""
    root = tool.get("outputSchema") or {}
    assert root, f"{tool['name']} publishes no outputSchema"
    schema = root
    for part in path:
        found = None
        for branch in branches(schema, root):
            if part in (branch.get("properties") or {}):
                found = branch["properties"][part]
        assert found is not None, f"{tool['name']}: the output schema has no field {'.'.join(path)}"
        schema = found
        items = [b.get("items") for b in branches(schema, root) if b.get("items")]
        if items:
            schema = items[0]
    names: set[str] = set()
    for branch in branches(schema, root):
        names.update((branch.get("properties") or {}).keys())
    return names


def check_title(tool: dict, title: str) -> None:
    titles = [t for t in (tool.get("title"), (tool.get("annotations") or {}).get("title")) if t is not None]
    assert titles, f"{tool['name']}: no title; CONTRACT.md gives {title!r}"
    assert all(t == title for t in titles), f"{tool['name']}: title must be {title!r}, got {titles}"


def check_read_annotations(tool: dict) -> None:
    hints = tool.get("annotations") or {}
    name = tool["name"]
    assert hints.get("readOnlyHint") is True, f"{name}: readOnlyHint must be true"
    assert hints.get("openWorldHint") is False, f"{name}: openWorldHint must be false (it defaults to true)"
    assert hints.get("destructiveHint") is None, f"{name}: leave destructiveHint out on a read-only tool"
    assert hints.get("idempotentHint") in (None, False), f"{name}: leave idempotentHint out on a read-only tool"


def check_description(tool: dict) -> None:
    text = tool.get("description") or ""
    assert 40 <= len(text) <= 400, (
        f"{tool['name']}: the description must be 40 to 400 characters, it has {len(text)}"
    )


# ------------------------------------------------------------------ the server


class Server:
    """One running server process and one MCP client session, used from sync tests."""

    def __init__(self, *flags: str, root: Path = S3_LOGS, reports: Path | None = None):
        self.root = Path(root)
        self.reports = reports
        args = ["--root", str(self.root)]
        if reports is not None:
            args += ["--reports", str(reports)]
        self.command = server_command() + args + list(flags)
        self._log_dir = tempfile.mkdtemp(prefix="log-triage-checks-")
        self.stderr_path = Path(self._log_dir) / "server-stderr.log"
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: Client | None = None
        self._stop: asyncio.Event | None = None
        self._failure: str | None = None
        self._tools: dict[str, dict] | None = None

    # lifecycle

    def start(self) -> "Server":
        if self._thread is not None:
            return self
        self._loop = asyncio.new_event_loop()
        ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, args=(ready,), daemon=True)
        self._thread.start()
        if not ready.wait(START_TIMEOUT + 30):
            self._failure = f"no answer to initialization within {START_TIMEOUT + 30} s"
        return self

    def _run_loop(self, ready: threading.Event) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._session(ready))

    async def _session(self, ready: threading.Event) -> None:
        self._stop = asyncio.Event()
        transport = StdioTransport(
            command=self.command[0], args=self.command[1:], keep_alive=False, log_file=self.stderr_path
        )
        try:
            async with Client(transport, init_timeout=START_TIMEOUT, timeout=CALL_TIMEOUT) as client:
                self._client = client
                ready.set()
                await self._stop.wait()
        except BaseException as exc:  # a server that never starts ends up here
            if self._client is None:
                self._failure = f"{type(exc).__name__}: {exc}"
        finally:
            ready.set()

    def close(self) -> None:
        if self._loop is not None and self._stop is not None and self._thread is not None:
            self._loop.call_soon_threadsafe(self._stop.set)
            self._thread.join(timeout=30)
        shutil.rmtree(self._log_dir, ignore_errors=True)

    def require(self) -> Client:
        self.start()
        if self._failure is not None or self._client is None:
            pytest.fail(self.failure_message(), pytrace=False)
        return self._client

    def stderr_tail(self, lines: int = 15) -> str:
        try:
            text = self.stderr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "(nothing)"
        return "\n".join(text.splitlines()[-lines:]) or "(nothing)"

    def failure_message(self) -> str:
        return (
            "The server did not start, so this check can't run.\n"
            f"Command: {shlex.join(self.command)}\n"
            f"Error: {self._failure}\n"
            f"Last lines on the server's stderr:\n{self.stderr_tail()}\n"
            "Task 2 creates the server in solution/ (see the practice README). "
            "To test another build, set LOG_TRIAGE_CMD to its command as a JSON array."
        )

    def _run(self, coro):
        client = self.require()
        future = asyncio.run_coroutine_threadsafe(coro(client), self._loop)
        return future.result(CALL_TIMEOUT + 30)

    # MCP

    @property
    def server_info(self):
        return self.require().server_info

    @property
    def instructions(self) -> str | None:
        return self.require().instructions

    @property
    def protocol_version(self):
        return self.require().protocol_version

    def tools(self) -> dict[str, dict]:
        if self._tools is None:
            listed = self._run(lambda client: client.list_tools())
            self._tools = {tool.name: tool.model_dump(mode="json", by_alias=True) for tool in listed}
        return self._tools

    def tool(self, name: str, task: str | None = None) -> dict:
        tools = self.tools()
        if name not in tools:
            where = f" {task}" if task else ""
            pytest.fail(f"{name} is not in tools/list (found: {sorted(tools) or 'no tools'}).{where}", pytrace=False)
        return tools[name]

    def call(self, name: str, arguments: dict) -> Reply:
        reply = Reply(tool=name, arguments=arguments)

        async def go(client: Client):
            return await client.call_tool_mcp(name, arguments, timeout=CALL_TIMEOUT)

        try:
            result = self._run(go)
        except MCPError as exc:
            reply.error = exc
            return reply
        reply.is_error = bool(result.is_error)
        reply.structured = result.structured_content
        for block in result.content:
            if getattr(block, "type", None) == "text":
                reply.texts.append(block.text)
            else:
                reply.other_blocks += 1
        return reply
