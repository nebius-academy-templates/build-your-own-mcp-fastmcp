"""`start` launches a server for one test and stops it afterwards."""

from __future__ import annotations

import pytest

from support import Server


@pytest.fixture
def start(tmp_path_factory):
    servers: list[Server] = []

    def launch(transport: str = "stdio", enabled: bool = True, extra: dict[str, str] | None = None) -> Server:
        server = Server(tmp_path_factory.mktemp("p5"), transport, enabled, extra)
        servers.append(server)
        return server

    yield launch
    for server in servers:
        server.close()
