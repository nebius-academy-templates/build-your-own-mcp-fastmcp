"""Task 2: the scan store: version, instructions, --scan-ttl, scan_id and expires_at."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from support import (
    P1_INSTRUCTIONS, S3_LOGS, SCAN_ID_RE, TIME_RE, Server, ok, output_fields, p2_sentence,
)

TASK = "Task 2 adds scan_id and expires_at to summarize_logs."
SMALL = {"path": "vms/web-01/archive/php-fpm-2026-08-30.log.gz"}


def version_tuple(text: str) -> tuple[int, int, int]:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", text or "")
    assert match, f"the server version must look like 0.2.0, got {text!r}"
    return tuple(int(part) for part in match.groups())


def seconds_from_now(text: str) -> float:
    assert isinstance(text, str) and TIME_RE.match(text), (
        f"expires_at must be a UTC time like 2026-01-31T14:00:00Z, got {text!r}"
    )
    when = dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)
    return (when - dt.datetime.now(dt.timezone.utc)).total_seconds()


def check_instructions(running: Server, lifetime: str) -> None:
    text = running.instructions or ""
    want = f"{P1_INSTRUCTIONS} {p2_sentence(lifetime)}"
    if version_tuple(running.server_info.version) < (0, 3, 0):
        assert text == want, (
            "instructions must be the practice 1 text, a space, and the scan sentence of "
            "CONTRACT.md, Instructions, with the configured lifetime.\n"
            f"expected: {want!r}\ngot:      {text!r}"
        )
        assert len(text) < 800, f"instructions must stay under 800 characters, got {len(text)}"
    else:
        assert text.startswith(want), "later instructions must keep the practice 2 text first"


def test_server_version_is_at_least_0_2_0(server):
    version = server.server_info.version
    assert version_tuple(version) >= (0, 2, 0), f"the server version must be 0.2.0 or later, got {version!r}"


def test_instructions_name_the_default_lifetime(server):
    check_instructions(server, "15 minutes")


@pytest.mark.parametrize("seconds, lifetime", [
    ("120", "2 minutes"),
    ("60", "1 minute"),
    ("150", "150 seconds"),
    ("59", "59 seconds"),
    ("1", "1 second"),
    ("7200", "120 minutes"),
], ids=["exact-minutes", "singular-minute", "partial-minute", "under-a-minute", "singular-second", "hours-in-minutes"])
def test_instructions_follow_scan_ttl(tmp_path, seconds, lifetime):
    running = Server("--scan-ttl", seconds, root=S3_LOGS, reports=tmp_path / "reports")
    try:
        check_instructions(running, lifetime)
    finally:
        running.close()


def test_summarize_logs_output_schema_has_the_scan_fields(server):
    fields = output_fields(server.tool("summarize_logs", TASK))
    assert {"scan_id", "expires_at"} <= fields, (
        f"summarize_logs: the output schema lacks {sorted({'scan_id', 'expires_at'} - fields)}"
    )


def scan_id_of(result: dict) -> str:
    scan_id = result.get("scan_id")
    assert isinstance(scan_id, str) and SCAN_ID_RE.match(scan_id), (
        f"summarize_logs must return a scan_id of s_ and 16 lowercase hex characters, got {scan_id!r}. {TASK}"
    )
    return scan_id


def test_summarize_logs_returns_a_scan_id(server):
    scan_id_of(ok(server.call("summarize_logs", SMALL)))


def test_scan_ids_are_random(server):
    ids = [scan_id_of(ok(server.call("summarize_logs", SMALL))) for _ in range(100)]
    assert all(isinstance(i, str) and SCAN_ID_RE.match(i) for i in ids), f"bad scan_id among {ids[:5]}"
    assert len(set(ids)) == 100, "100 scans of the same file must give 100 different scan_ids"
    assert ids != sorted(ids) and ids != sorted(ids, reverse=True), (
        "scan_ids come out in sorted order; they must be random, not a counter or a clock"
    )
    shared = max(len(_common_prefix(a, b)) for a, b in zip(ids, ids[1:]))
    assert shared < 12, (
        f"two scan_ids in a row share their first {shared} characters; they must be random"
    )


def _common_prefix(a: str, b: str) -> str:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return "".join(out)


def test_expires_at_is_now_plus_the_default_lifetime(server):
    result = ok(server.call("summarize_logs", SMALL))
    scan_id_of(result)
    left = seconds_from_now(result.get("expires_at"))
    assert 900 - 3 <= left <= 900 + 2, (
        f"expires_at must be the call time plus 900 seconds (the default --scan-ttl), "
        f"within two seconds; it is {left:.0f} seconds from now"
    )


def test_expires_at_follows_scan_ttl(short_server):
    result = ok(short_server.call("summarize_logs", SMALL))
    left = seconds_from_now(result.get("expires_at"))
    assert -1 - 2 <= left <= 2 + 2, (
        f"with --scan-ttl 2, expires_at must be the call time plus 2 seconds, within two seconds; "
        f"it is {left:.0f} seconds from now"
    )


def test_the_same_call_twice_gives_two_scans(server):
    first = scan_id_of(ok(server.call("summarize_logs", SMALL)))
    second = scan_id_of(ok(server.call("summarize_logs", SMALL)))
    assert first != second, "every summarize_logs call makes a new scan with its own scan_id"
