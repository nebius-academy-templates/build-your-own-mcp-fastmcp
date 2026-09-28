"""Servers shared by the tests of one file. Each starts on first use."""

from __future__ import annotations

import pytest

from support import S3_LOGS, Server, build_tree


@pytest.fixture(scope="session")
def tree_root(tmp_path_factory):
    """A small log root built from expected.json, for folder-level checks."""
    return build_tree(tmp_path_factory.mktemp("tree") / "logs root")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The server on s3_logs, writing findings to a temporary folder."""
    running = Server(root=S3_LOGS, reports=tmp_path_factory.mktemp("reports"))
    yield running
    running.close()


@pytest.fixture(scope="module")
def tree_server(tree_root, tmp_path_factory):
    """The server on the temporary log root."""
    running = Server(root=tree_root, reports=tmp_path_factory.mktemp("reports"))
    yield running
    running.close()


@pytest.fixture(scope="module")
def servers(server, tree_server):
    """Both servers, by the root name expected.json uses."""
    return {"s3_logs": server, "tree": tree_server}
