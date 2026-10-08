"""Install DataViz MCP into common JSON MCP client configurations."""

import json
import os
import sys
from pathlib import Path

SERVER_NAME = "dataviz-mcp"


def client_config_path(client: str) -> Path:
    """Return the default MCP config path for a supported client."""
    paths = {
        "cursor": Path("~/.cursor/mcp.json").expanduser(),
        "vscode": Path(".vscode/mcp.json"),
        "windsurf": Path("~/.codeium/windsurf/mcp_config.json").expanduser(),
        "cline": Path(os.getenv("CLINE_MCP_SETTINGS_PATH", "~/.cline/data/settings/cline_mcp_settings.json")).expanduser(),
        "gemini": Path("~/.gemini/settings.json").expanduser(),
        "kiro": Path("~/.kiro/settings/mcp.json").expanduser(),
        "copilot": Path(os.getenv("COPILOT_HOME", "~/.copilot")).expanduser() / "mcp-config.json",
        "claude-desktop": (
            Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
            if sys.platform == "win32" and "APPDATA" in os.environ
            else Path("~/.config/Claude/claude_desktop_config.json").expanduser()
        ),
    }
    if client not in paths:
        raise ValueError(
            f"Unsupported client {client!r}. Choose cursor, vscode, claude-desktop, windsurf, cline, gemini, kiro, or copilot."
        )
    return paths[client]


def merge_mcp_server(config_path: Path, command: str) -> tuple[bool, dict]:
    """Create or update only this server's JSON entry, preserving all others."""
    if config_path.exists():
        data = json.loads(config_path.read_text(encoding="utf-8"))
    else:
        data = {}
    servers = data.setdefault("mcpServers", {})
    entry = {"command": command, "args": ["mcp"]}
    unchanged = servers.get(SERVER_NAME) == entry
    if not unchanged:
        servers[SERVER_NAME] = entry
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return unchanged, entry
