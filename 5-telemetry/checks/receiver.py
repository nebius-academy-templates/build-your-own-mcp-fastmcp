"""Collects OTLP/HTTP protobuf spans for the black-box checks and the trace viewer."""

from __future__ import annotations

import gzip
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.common.v1.common_pb2 import KeyValue
from opentelemetry.proto.trace.v1.trace_pb2 import Span

MAX_BODY = 16 << 20


@dataclass
class Record:
    span: Span
    resource: dict[str, Any]


def attributes(kvs: list[KeyValue]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for kv in kvs:
        kind = kv.value.WhichOneof("value")
        if kind in ("string_value", "int_value", "bool_value", "double_value"):
            result[kv.key] = getattr(kv.value, kind)
        else:
            result[kv.key] = str(kv.value)
    return result


def hex_id(raw: bytes) -> str:
    return raw.hex()


class Receiver:
    """An OTLP/HTTP endpoint at /v1/traces on a loopback port. Spans are kept by trace and span ID."""

    def __init__(self, port: int = 0):
        self._lock = threading.Lock()
        self._records: dict[str, Record] = {}
        self.posts = 0
        receiver = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                if self.path != "/v1/traces" or length > MAX_BODY:
                    self.send_error(404)
                    return
                data = self.rfile.read(length)
                try:
                    if self.headers.get("Content-Encoding") == "gzip":
                        data = gzip.decompress(data)
                    batch = ExportTraceServiceRequest.FromString(data)
                except Exception:
                    self.send_error(400, "invalid OTLP protobuf")
                    return
                receiver._add(batch)
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()  # an empty protobuf response is valid

            def do_GET(self) -> None:  # noqa: N802
                self.send_error(404)

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def start(self) -> "Receiver":
        self._thread.start()
        return self

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def _add(self, batch: ExportTraceServiceRequest) -> None:
        with self._lock:
            self.posts += 1
            for resource_spans in batch.resource_spans:
                resource = attributes(resource_spans.resource.attributes)
                for scope in resource_spans.scope_spans:
                    for span in scope.spans:
                        self._records[hex_id(span.trace_id) + ":" + hex_id(span.span_id)] = Record(span, resource)

    def snapshot(self) -> list[Record]:
        with self._lock:
            rows = list(self._records.values())
        return sorted(rows, key=lambda row: row.span.start_time_unix_nano)
