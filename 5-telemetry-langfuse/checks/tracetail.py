"""Prints snapshots of local OTLP traces across export batches, one line per span, under its parent."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from typing import Any

from opentelemetry.proto.trace.v1.trace_pb2 import Span, Status

from receiver import Receiver, Record, attributes, hex_id


def shown(values: dict[str, Any]) -> str:
    parts = []
    for key in sorted(values):
        value = values[key]
        parts.append(f"{key}:{str(value).lower() if isinstance(value, bool) else value}")
    return "map[" + " ".join(parts) + "]"


def key(row: Record) -> str:
    return hex_id(row.span.trace_id) + ":" + hex_id(row.span.span_id)


def parent_key(row: Record) -> str:
    return hex_id(row.span.trace_id) + ":" + hex_id(row.span.parent_span_id)


def show(rows: list[Record]) -> None:
    print(f"\nSnapshot: {len(rows)} spans, buffered across batches", flush=True)
    by_id = {key(row): row for row in rows}
    children: dict[str, list[Record]] = {}
    for row in rows:
        children.setdefault(parent_key(row), []).append(row)
    seen: set[str] = set()

    def line(row: Record, depth: int) -> None:
        if key(row) in seen:
            return
        seen.add(key(row))
        s = row.span
        print(f"{'  ' * depth}{s.name} {Span.SpanKind.Name(s.kind)} "
              f"{(s.end_time_unix_nano - s.start_time_unix_nano) / 1e6:.3f} ms "
              f"trace={hex_id(s.trace_id)} span={hex_id(s.span_id)} parent={hex_id(s.parent_span_id)} "
              f"status={Status.StatusCode.Name(s.status.code)} attrs={shown(attributes(s.attributes))} "
              f"resource={shown(row.resource)}", flush=True)
        for child in children.get(key(row), []):
            line(child, depth + 1)

    for row in rows:
        if parent_key(row) not in by_id:
            if row.span.parent_span_id:
                print(f"External or not-yet-received parent: {parent_key(row)}", flush=True)
            line(row, 0)
    for row in rows:
        line(row, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description="A local OTLP/HTTP receiver that prints the spans it gets.")
    parser.add_argument("--port", type=int, default=4318, help="loopback OTLP port (default: 4318)")
    port = parser.parse_args().port
    try:
        receiver = Receiver(port).start()
    except OSError as error:
        print(error, file=sys.stderr)
        sys.exit(1)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    print(f"OTLP receiver: {receiver.url}/v1/traces (Ctrl-C to stop)", flush=True)
    count = -1
    while True:
        stopping = stop.wait(1)
        if stopping:
            receiver.close()
        rows = receiver.snapshot()
        if len(rows) != count:
            count = len(rows)
            if count:
                show(rows)
        if stopping:
            return


if __name__ == "__main__":
    main()
