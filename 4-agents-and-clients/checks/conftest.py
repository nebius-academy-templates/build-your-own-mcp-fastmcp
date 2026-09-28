"""The server over HTTP, shared by the tests of one file. It starts on first use."""

from __future__ import annotations

import pytest

from support import HttpServer


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The server on s3_logs with the checks' tokens, writing findings to a temporary folder."""
    running = HttpServer(reports=tmp_path_factory.mktemp("reports"))
    yield running
    running.close()
