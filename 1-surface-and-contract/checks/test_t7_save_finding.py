"""Task 7: save_finding and the --read-only switch."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from support import (
    S3_LOGS, TIME_RE, Server, branches, check_description, check_enum, check_plain, check_title, ok,
    output_fields, refused_by_schema, required_of, resolve, types_of,
)

TASK = "Task 7 registers save_finding."
EVIDENCE = [
    {"file": "pods/provisioner-2/archive/app-2026-08-30.log.gz", "line": 37, "note": "the first warning of the day"},
    {"file": "vms/web-01/archive/php-fpm-2026-08-30.log.gz", "line": 1, "note": "a restart right before it"},
]
GOOD = {"title": "A title", "severity": "low", "summary": "A summary.", "evidence": EVIDENCE[:1]}


def rendered(title, severity, saved, summary, evidence):
    lines = [f"# {title}", "", f"- Severity: {severity}", f"- Saved: {saved}", "", summary, "",
             "## Evidence", ""]
    lines += [f"- `{item['file']}` line {item['line']}: {item['note']}" for item in evidence]
    return "\n".join(lines) + "\n"


def near_now(text: str) -> bool:
    when = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return abs((dt.datetime.now(dt.timezone.utc) - when).total_seconds()) < 120


def version_tuple(text: str) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", text)[:3]]
    return tuple((parts + [0, 0, 0])[:3])


@pytest.fixture(scope="module")
def read_only(tmp_path_factory):
    running = Server("--read-only", root=S3_LOGS, reports=tmp_path_factory.mktemp("read-only-reports"))
    yield running
    running.close()


def test_save_finding_title_and_annotations(server):
    tool = server.tool("save_finding", TASK)
    check_title(tool, "Save a finding")
    hints = tool.get("annotations") or {}
    destructive = hints.get("destructiveHint")
    if version_tuple(server.server_info.version) < (0, 2, 0):
        assert destructive is True, (
            "save_finding: destructiveHint must be true in version 0.1 because a repeated title overwrites its report"
        )
    else:
        assert isinstance(destructive, bool), (
            "save_finding: destructiveHint must be an explicit boolean in version 0.2 or later"
        )
    assert hints.get("openWorldHint") is False, "save_finding: openWorldHint must be false, written out"
    assert hints.get("readOnlyHint") in (None, False), "save_finding: readOnlyHint must be false"
    assert hints.get("idempotentHint") in (None, False), "save_finding: idempotentHint must be false"


def test_save_finding_description_length(server):
    check_description(server.tool("save_finding", TASK))


def test_save_finding_parameters(server):
    tool = server.tool("save_finding", TASK)
    check_plain(tool, "title", "string", minLength=3, maxLength=120)
    check_enum(tool, "severity", ["low", "medium", "high", "critical"])
    check_plain(tool, "summary", "string", minLength=1, maxLength=4000)
    check_plain(tool, "evidence", "array", minItems=1, maxItems=20)
    assert required_of(tool) == {"title", "severity", "summary", "evidence"}, (
        f"save_finding: title, severity, summary and evidence are required, got {sorted(required_of(tool))}"
    )
    root = tool["inputSchema"]
    items = [b.get("items") for b in branches(root["properties"]["evidence"], root) if b.get("items")]
    assert items, "save_finding.evidence: the schema must describe its items"
    item = resolve(items[0], root)
    props = item.get("properties") or {}
    assert set(item.get("required") or []) == {"file", "line", "note"}, (
        f"save_finding.evidence items: file, line and note are required, got {item.get('required')}"
    )
    for name, kind, bounds in [("file", "string", {"maxLength": 500}), ("line", "integer", {"minimum": 1}),
                               ("note", "string", {"minLength": 1, "maxLength": 300})]:
        assert name in props, f"save_finding.evidence items have no field {name!r}"
        assert types_of(props[name], root) == {kind}, (
            f"save_finding.evidence[].{name}: type must be exactly {kind!r}, got {sorted(types_of(props[name], root))}"
        )
        for key, want in bounds.items():
            got = resolve(props[name], root).get(key)
            assert got == want, f"save_finding.evidence[].{name}: {key} must be {want}, got {got}"


def test_save_finding_output_schema(server):
    fields = output_fields(server.tool("save_finding", TASK))
    assert {"name", "path", "created"} <= fields, f"save_finding: the output schema lacks {sorted({'name', 'path', 'created'} - fields)}"


@pytest.mark.parametrize("change, why", [
    ({"title": "ab"}, "title is at least 3 characters"),
    ({"title": "x" * 121}, "title is at most 120 characters"),
    ({"severity": "urgent"}, "severity is low, medium, high or critical"),
    ({"summary": ""}, "summary is at least 1 character"),
    ({"summary": "x" * 4001}, "summary is at most 4,000 characters"),
    ({"evidence": []}, "evidence has at least 1 item"),
    ({"evidence": EVIDENCE[:1] * 21}, "evidence has at most 20 items"),
    ({"evidence": [{**EVIDENCE[0], "line": 0}]}, "an evidence line is 1 or more"),
    ({"evidence": [{"file": EVIDENCE[0]["file"], "line": 3}]}, "an evidence item needs a note"),
    ({"evidence": [{**EVIDENCE[0], "note": ""}]}, "an evidence note is at least 1 character"),
    ({"evidence": [{**EVIDENCE[0], "note": "x" * 301}]}, "an evidence note is at most 300 characters"),
    ({"summary": None}, "summary is required"),
    ({"surprise": 1}, "save_finding has no parameter named surprise"),
], ids=["title-short", "title-long", "severity-unknown", "summary-empty", "summary-long",
        "evidence-empty", "evidence-21", "evidence-line-0", "evidence-no-note", "evidence-note-empty",
        "evidence-note-long", "no-summary", "unknown-argument"])
def test_save_finding_refuses_bad_arguments(server, change, why):
    server.tool("save_finding", TASK)
    args = {**GOOD, **change}
    args = {key: value for key, value in args.items() if value is not None}
    refused_by_schema(server.call("save_finding", args), why)
    assert not list(server.reports.glob("a-title*")), "a refused save_finding call wrote a file"


def test_save_finding_writes_the_markdown_file(server):
    server.tool("save_finding", TASK)
    title = "Warnings climb after the morning restart"
    summary = "The warnings start right after a restart.\nThey stop by the evening."
    before = set(server.reports.iterdir())
    result = ok(server.call("save_finding", {
        "title": title, "severity": "medium", "summary": summary, "evidence": EVIDENCE,
    }))
    slug = "warnings-climb-after-the-morning-restart"
    assert result.get("name") == slug, f"save_finding: name must be the slug {slug!r}, got {result.get('name')!r}"
    assert result.get("path") == slug + ".md", f"save_finding: path must be {slug + '.md'!r}, got {result.get('path')!r}"
    created = result.get("created")
    assert isinstance(created, str) and TIME_RE.match(created) and near_now(created), (
        f"save_finding: created must be the current UTC time as YYYY-MM-DDTHH:MM:SSZ, got {created!r}"
    )
    written = set(server.reports.iterdir()) - before
    assert written == {server.reports / (slug + ".md")}, (
        f"save_finding must write exactly {slug}.md under --reports, it wrote {sorted(p.name for p in written)}"
    )
    content = (server.reports / (slug + ".md")).read_bytes().decode("utf-8")
    saved = re.search(r"^- Saved: (.*)$", content, re.M)
    assert saved, f"the finding has no '- Saved: <time>' line:\n{content}"
    assert saved.group(1) == created, f"the Saved time {saved.group(1)!r} must equal created {created!r}"
    want = rendered(title, "medium", created, summary, EVIDENCE)
    assert content == want, f"the finding file must be exactly:\n{want!r}\ngot:\n{content!r}"


@pytest.mark.parametrize("title, slug", [
    ("Newsletter queue stalls on Mondays!", "newsletter-queue-stalls-on-mondays"),
    ("  --Font loading glitches, 3 of them--  ", "font-loading-glitches-3-of-them"),
    ("!!!", "finding"),
    ("Ünïcode Title 42", "n-code-title-42"),
    ("İstanbul newsletter", "stanbul-newsletter"),
    ("a" * 59 + " b", "a" * 59),
    ("Thumbnails render slowly for large albums after every nightly rebuild",
     "thumbnails-render-slowly-for-large-albums-after-every-nightl"),
], ids=["punctuation", "leading-and-trailing", "no-letters", "non-ascii", "ascii-only-lowercase",
        "cut-then-trim", "cut-mid-word"])
def test_save_finding_names_the_file_after_the_title(server, title, slug):
    server.tool("save_finding", TASK)
    result = ok(server.call("save_finding", {**GOOD, "title": title}))
    assert result.get("name") == slug, f"the slug of {title!r} must be {slug!r}, got {result.get('name')!r}"
    assert (server.reports / (slug + ".md")).is_file(), f"{slug}.md was not written under --reports"


def test_save_finding_creates_the_reports_folder(tmp_path):
    reports = tmp_path / "new" / "reports folder"
    running = Server(root=S3_LOGS, reports=reports)
    try:
        running.tool("save_finding", TASK)
        ok(running.call("save_finding", GOOD))
    finally:
        running.close()
    assert (reports / "a-title.md").is_file(), "save_finding must create a missing --reports folder"


def test_read_only_removes_only_save_finding(server, read_only):
    server.tool("save_finding", TASK)
    normal = set(server.tools())
    hidden = set(read_only.tools())
    assert hidden == normal - {"save_finding"}, (
        f"with --read-only the tools must be {sorted(normal - {'save_finding'})}, got {sorted(hidden)}"
    )


def test_read_only_refuses_a_save_finding_call(server, read_only):
    server.tool("save_finding", TASK)
    reply = read_only.call("save_finding", GOOD)
    assert reply.error is not None or (reply.is_error and reply.structured is None), (
        f"with --read-only a save_finding call must fail as an unknown tool, got {reply.summary()}"
    )
    assert not list(read_only.reports.iterdir()), "with --read-only nothing may be written"
