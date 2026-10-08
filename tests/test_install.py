"""Regression tests for non-destructive MCP client setup."""

import json

from dataviz_mcp.install import SERVER_NAME
from dataviz_mcp.install import client_config_path
from dataviz_mcp.install import merge_mcp_server


def test_merge_preserves_other_servers_and_is_idempotent(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(json.dumps({"mcpServers": {"other": {"command": "other"}}}), encoding="utf-8")

    unchanged, entry = merge_mcp_server(path, "/opt/bin/pls")
    assert unchanged is False
    assert entry == {"command": "/opt/bin/pls", "args": ["mcp"]}
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "other"}
    assert data["mcpServers"][SERVER_NAME] == entry

    assert merge_mcp_server(path, "/opt/bin/pls")[0] is True


def test_common_client_paths_are_known():
    for client in ("cursor", "vscode", "claude-desktop", "windsurf", "cline", "gemini", "kiro", "copilot"):
        assert client_config_path(client)
