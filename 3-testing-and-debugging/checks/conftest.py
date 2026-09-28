"""Log roots and servers shared by the tests. Each server starts on first use."""

from __future__ import annotations

import pytest

from support import S3_LOGS, Server, build_tree


@pytest.fixture(scope="session")
def tree(tmp_path_factory):
    """A small log root of made-up files (expected.json, trees.tree)."""
    return build_tree("tree", tmp_path_factory.mktemp("tree"))


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The server on s3_logs, writing findings to a temporary folder."""
    running = Server(root=S3_LOGS, reports=tmp_path_factory.mktemp("reports"))
    yield running
    running.close()


@pytest.fixture(scope="module")
def tree_server(tree, tmp_path_factory):
    running = Server(root=tree.root, reports=tmp_path_factory.mktemp("reports"))
    yield running
    running.close()


@pytest.fixture(scope="module")
def servers(server, tree_server):
    """The servers by the root name expected.json uses."""
    return {"s3_logs": server, "tree": tree_server}
