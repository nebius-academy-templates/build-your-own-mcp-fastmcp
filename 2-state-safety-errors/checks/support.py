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
import queue
import re
import shlex
import shutil
import subprocess
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
SCAN_ID_RE = re.compile(r"^s_[0-9a-f]{16}$")
NOT_FOUND = -32602

P1_INSTRUCTIONS = (
    "Log Triage reads log files under one folder. Start with list_logs to see what is there. "
    "Use summarize_logs on a file or folder, with since and until when you know the time, to get "
    "counts and message groups instead of raw lines. Use search_logs to find the lines that match a "
    "pattern. Record a conclusion with save_finding and cite a file and line for every piece of "
    "evidence. All times are UTC."
)


def p2_sentence(lifetime: str) -> str:
    return (
        f"summarize_logs returns a scan_id that works for {lifetime}; pass it to group_lines to read "
        "one group's lines without scanning again. Use read_lines for the lines around one line. "
        "Saved findings are listed at triage://reports."
    )


# ------------------------------------------------------------------ contract texts (CONTRACT.md, Errors)


def e1(path: str) -> str:
    return (f'path "{path}" is outside the log root. Pass a path relative to the log root; '
            f'list_logs with path "." shows what is there.')


def e2(path: str) -> str:
    return f'path "{path}" does not exist under the log root. Call list_logs to see what is there.'


def e3(field_name: str) -> str:
    return f"{field_name} must be a date like 2026-01-31 or a time like 2026-01-31T14:00:00Z."


E4 = "until must be later than since."


def e5(field_name: str) -> str:
    return (f"{field_name} is not a valid regular expression. Escape special characters such as ( [ . * "
            f"with a backslash, or search for a plain word.")


def e6(scan_id: str) -> str:
    return f'scan "{scan_id}" is unknown or has expired. Call summarize_logs again for a new scan_id.'


def e8(line: int, file: str, total: int) -> str:
    return f'line {line} is past the end of "{file}", which has {total} lines.'


def e9(name: str) -> str:
    return f'a finding named "{name}" already exists. Choose a different title.'


def e10(path: str) -> str:
    return f'"{path}" is a folder. This needs one file; call list_logs to pick one.'


# ------------------------------------------------------------------ command and trees


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


def child_env() -> dict[str, str]:
    """The checks' environment without the virtualenv, so a nested `uv run` picks the server's."""
    return {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}


def calls_for(tool: str, kind: str = "result") -> list[str]:
    return [call_id for call_id, call in CALLS.items() if call["tool"] == tool and kind in call]


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


def make_entry(entry: dict, base: Path) -> None:
    """One file or link of a temporary tree; expected.json's 'about' lists the kinds."""
    target = base / entry["path"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if "symlink" in entry:
        target.symlink_to(entry["symlink"])
    elif "copy" in entry:
        shutil.copyfile(S3_LOGS / entry["copy"], target)
    elif "gunzip" in entry:
        target.write_bytes(gzip.decompress((S3_LOGS / entry["gunzip"]).read_bytes()))
    elif "bytes" in entry:
        target.write_bytes(entry["bytes"].encode("utf-8"))
    else:
        lines = list(entry["text"])
        if "fill" in entry:
            filler = entry["fill"]["char"] * entry["fill"]["count"]
            lines = [line.replace("{fill}", filler) for line in lines]
        block = "\n".join(lines) + "\n"
        repeat = entry.get("repeat", 1)
        if entry.get("numbered"):
            text = "".join(block.replace("{n}", str(i)) for i in range(1, repeat + 1))
        else:
            text = block * repeat
        data = text.encode("utf-8")
        if entry.get("gzip"):
            data = gzip.compress(data, compresslevel=6, mtime=0)
            if entry.get("cut_half"):
                data = data[: len(data) // 2]
        target.write_bytes(data)
        if "size" in entry:
            with open(target, "r+b") as fh:
                fh.truncate(entry["size"])


@dataclass
class Tree:
    base: Path   # the folder the entries live in
    root: Path   # the log root inside it


def build_tree(name: str, dest: Path) -> Tree:
    spec = EXPECTED["trees"][name]
    base = dest.resolve()
    base.mkdir(parents=True, exist_ok=True)
    for entry in spec["entries"]:
        make_entry(entry, base)
    return Tree(base=base, root=base / spec["root"])


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


def tool_error(reply: Reply, text: str, root: Path | None = None) -> None:
    """Refused by the tool itself with exactly the contract's text."""
    assert reply.error is None, (
        f"{reply.label()} must come back as a tool error (a result with isError: true), "
        f"got {reply.summary()}"
    )
    assert reply.is_error, f"{reply.label()} was accepted; it must answer: {text}"
    assert reply.structured is None, f"{reply.label()} is an error but carries structuredContent"
    got = " ".join(reply.texts)
    assert got == text, (
        f"{reply.label()}: the error text must be exactly the contract's (CONTRACT.md, Errors).\n"
        f"expected: {text!r}\ngot:      {got!r}"
    )
    if root is not None and str(root) not in json.dumps(reply.arguments):
        assert str(root) not in got, f"{reply.label()}: the error text shows the log root's absolute path"


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


def validated(server: "Server", tool: str, result: dict, where: str) -> dict:
    try:
        jsonschema.validate(result, server.tool(tool).get("outputSchema") or {})
    except jsonschema.ValidationError as exc:
        pytest.fail(f"{where}: structuredContent does not match the outputSchema: {exc.message}")
    return result


def run_call(server: "Server", call_id: str) -> tuple[Reply, dict]:
    """Make one expected.json call; a group_lines call scans first. Returns the reply and the places."""
    call = CALLS[call_id]
    places = {"root": str(server.root)}
    if call["tool"] == "group_lines":
        places["scan_id"] = server.scan(fill(call["scan"], places))
        args = {"scan_id": places["scan_id"], "group_id": call["group_id"], **call["args"]}
    else:
        args = fill(call["args"], places)
    return server.call(call["tool"], args), places


def check_answer(server: "Server", call_id: str, hint: str = "") -> dict:
    call = CALLS[call_id]
    reply, places = run_call(server, call_id)
    where = f"{call['tool']} {call_id}"
    result = validated(server, call["tool"], ok(reply), where)
    want = fill(call["result"], places)
    try:
        if call.get("compare") == "path and format":
            got = [(f.get("path"), f.get("format")) for f in result.get("files", [])]
            assert got == [(f["path"], f["format"]) for f in want["files"]], f"{where}: files differ: {got}"
            same({k: v for k, v in result.items() if k != "files"},
                 {k: v for k, v in want.items() if k != "files"}, where)
        else:
            same(result, want, where)
    except AssertionError as exc:
        if not hint:
            raise
        raise AssertionError(f"{exc}\n{hint}") from None
    return result


def check_error(server: "Server", call_id: str) -> None:
    reply, places = run_call(server, call_id)
    tool_error(reply, fill(CALLS[call_id]["error"], places), server.root)


def not_found(reply: "ResourceReply", uri: str) -> None:
    """The protocol's resource-not-found error, with the URI in its message or in data.uri."""
    assert reply.error is not None, (
        f"reading {uri} must fail with the resource-not-found error (JSON-RPC {NOT_FOUND}), "
        f"got a result: {str(reply.contents)[:200]}"
    )
    error = reply.error.error
    assert error.code == NOT_FOUND, (
        f"reading {uri}: the error code must be {NOT_FOUND}, got {error.code} ({error.message[:200]})"
    )
    data_uri = error.data.get("uri") if isinstance(error.data, dict) else None
    assert uri in error.message or data_uri == uri, (
        f"reading {uri}: the error must carry the URI in its message or in data.uri, "
        f"got message {error.message!r} and data {error.data!r}"
    )


def masked(reply: Reply, root: Path) -> None:
    """An unexpected error: a tool error that shows nothing of what went wrong inside."""
    assert reply.error is None and reply.is_error, (
        f"{reply.label()} must come back as a tool error, got {reply.summary()}"
    )
    assert reply.structured is None, f"{reply.label()} is an error but carries structuredContent"
    text = " ".join(reply.texts)
    for leak in (str(root), "Errno", "Traceback", "Not a gzipped file", "BadGzipFile", "gzip: invalid header"):
        assert leak not in text, (
            f"{reply.label()}: an unexpected error must be masked (CONTRACT.md, Errors), "
            f"but the text shows {leak!r}: {text[:300]!r}"
        )


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


@dataclass
class ResourceReply:
    uri: str
    error: MCPError | None = None
    contents: list[dict] = field(default_factory=list)

    def document(self) -> Any:
        """The one text content, parsed as JSON."""
        assert self.error is None, (
            f"reading {self.uri} failed: JSON-RPC error {self.error.error.code}: "
            f"{self.error.error.message[:300]}. Task 5 adds the resources."
        )
        assert len(self.contents) == 1, f"reading {self.uri} must give one content, got {len(self.contents)}"
        try:
            return json.loads(self.contents[0].get("text") or "")
        except json.JSONDecodeError:
            pytest.fail(f"reading {self.uri}: the text is not JSON: {self.contents[0].get('text', '')[:200]!r}")

    def mime_type(self) -> str | None:
        return self.contents[0].get("mimeType") if self.contents else None


class Server:
    """One running server process and one MCP client session, used from sync tests."""

    def __init__(self, *flags: str, root: Path = S3_LOGS, reports: Path | None = None, task: str = "Task 2"):
        self.root = Path(root).resolve()
        self.reports = reports
        args = ["--root", str(root)]
        if reports is not None:
            args += ["--reports", str(reports)]
        self.command = server_command() + args + list(flags)
        self.task = task
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
            f"{self.task} (see the practice README) must leave a server that starts with these flags. "
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

    @staticmethod
    def _reply(name: str, arguments: dict, result: Any) -> Reply:
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

    def call(self, name: str, arguments: dict) -> Reply:
        async def go(client: Client):
            try:
                return await client.call_tool_mcp(name, arguments, timeout=CALL_TIMEOUT)
            except MCPError as exc:
                return exc

        return self._reply(name, arguments, self._run(go))

    def call_many(self, name: str, arguments: list[dict]) -> list[Reply]:
        """The same tool called with each argument set at once, over one session."""
        async def one(client: Client, args: dict):
            try:
                return await client.call_tool_mcp(name, args, timeout=CALL_TIMEOUT)
            except MCPError as exc:
                return exc

        async def go(client: Client):
            return await asyncio.gather(*(one(client, args) for args in arguments))

        return [self._reply(name, args, result) for args, result in zip(arguments, self._run(go))]

    def scan(self, arguments: dict) -> str:
        """summarize_logs, returning its scan_id."""
        self.tool("summarize_logs")
        result = ok(self.call("summarize_logs", arguments))
        scan_id = result.get("scan_id")
        assert isinstance(scan_id, str) and SCAN_ID_RE.match(scan_id), (
            f"summarize_logs must return a scan_id like s_ and 16 lowercase hex characters, got {scan_id!r}. "
            "Task 2 adds it."
        )
        return scan_id

    def require_template(self, uri_template: str) -> None:
        listed = [item.get("uriTemplate") for item in self.templates()]
        if uri_template not in listed:
            pytest.fail(f"resources/templates/list has no {uri_template} (found: {listed or 'none'}). "
                        "Task 5 adds the resources.", pytrace=False)

    def resources(self) -> list[dict]:
        listed = self._run(lambda client: client.list_resources())
        return [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in listed]

    def templates(self) -> list[dict]:
        listed = self._run(lambda client: client.list_resource_templates())
        return [item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in listed]

    def read(self, uri: str) -> ResourceReply:
        async def go(client: Client):
            try:
                return await client.read_resource_mcp(uri)
            except MCPError as exc:
                return exc

        result = self._run(go)
        if isinstance(result, MCPError):
            return ResourceReply(uri=uri, error=result)
        dumped = result.model_dump(mode="json", by_alias=True, exclude_none=True)
        return ResourceReply(uri=uri, contents=dumped.get("contents") or [])


# ------------------------------------------------------------------ raw frames


ENVELOPE = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientInfo": {"name": "log-triage-checks", "version": "2"},
    "io.modelcontextprotocol/clientCapabilities": {},
}


def raw_exchange(root: Path, reports: Path, requests: list[tuple[str, dict]]) -> list[dict]:
    """Send server/discover and then each (method, params) as one JSON-RPC line; return the answers.

    The client libraries hide some result fields, so this talks to the server's
    stdin and stdout directly, in the 2026-07-28 protocol revision.
    """
    command = server_command() + ["--root", str(root), "--reports", str(reports)]
    stderr = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
        env=child_env(), bufsize=0,
    )
    lines: queue.Queue = queue.Queue()

    def pump():
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    threading.Thread(target=pump, daemon=True).start()
    answers = []
    try:
        for number, (method, params) in enumerate([("server/discover", {})] + requests, start=1):
            frame = {"jsonrpc": "2.0", "id": number, "method": method,
                     "params": {**params, "_meta": ENVELOPE}}
            proc.stdin.write((json.dumps(frame) + "\n").encode("utf-8"))
            proc.stdin.flush()
            while True:
                try:
                    line = lines.get(timeout=START_TIMEOUT if number == 1 else CALL_TIMEOUT)
                except queue.Empty:
                    pytest.fail(f"no answer to {method} on the server's stdout", pytrace=False)
                if line is None:
                    stderr.seek(0)
                    err = stderr.read().decode("utf-8", "replace")[-800:]
                    pytest.fail(f"the server closed stdout before answering {method}. "
                                f"Command: {shlex.join(command)}\nstderr:\n{err}", pytrace=False)
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    pytest.fail(f"the server wrote a line to stdout that is not JSON-RPC: {line[:200]!r}")
                if message.get("id") == number:
                    break
            if number > 1:
                answers.append(message)
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr.close()
    return answers
