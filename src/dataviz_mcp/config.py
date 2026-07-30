"""Configuration for DataViz MCP."""

import hashlib
import logging
import os
import sys
from pathlib import Path

from pydantic import BaseModel
from pydantic import Field

logger = logging.getLogger("dataviz_mcp")

# Base port and window for the per-environment default. The derived port lands
# in [_PORT_BASE, _PORT_BASE + _PORT_SPAN), keeping it near the historical 5077
# default while giving each Python environment its own deterministic port.
_PORT_BASE = 5077
_PORT_SPAN = 1000


def _default_user_dir() -> Path:
    return Path(os.getenv("DATAVIZ_MCP_USER_DIR", "~/.dataviz-mcp")).expanduser()


def default_panel_port() -> int:
    """Return the Panel server port for the active Python environment.

    An explicit ``DATAVIZ_MCP_PORT`` always wins. Otherwise the port is
    derived deterministically from the interpreter (``sys.prefix``) so that each
    environment gets its own server.

    This is what keeps ``pls`` executing snippets against the packages the user
    expects: the Panel server subprocess runs in the same interpreter as ``pls``
    itself, but a single fixed port would let an MCP client launched from one
    environment silently adopt a server already running in another. That server
    executes code against *its* installed packages, so an import the user just
    installed alongside ``pls`` shows up as missing. A per-environment port means
    different environments no longer collide on one server.
    """
    explicit = os.getenv("DATAVIZ_MCP_PORT")
    if explicit:
        return int(explicit)
    digest = hashlib.sha256(sys.prefix.encode("utf-8")).digest()
    return _PORT_BASE + int.from_bytes(digest[:2], "big") % _PORT_SPAN


def _resolve_external_url(port: int) -> str:
    """Resolve the external URL for the Panel server.

    Checks in priority order:
    1. ``DATAVIZ_MCP_EXTERNAL_URL``                          — explicit override (port-inclusive).
    2. ``JUPYTERHUB_HOST`` + ``JUPYTERHUB_SERVICE_PREFIX``         — JupyterHub with jupyter-server-proxy.
       Note: ``JUPYTERHUB_SERVICE_PREFIX`` is set automatically by JupyterHub, but ``JUPYTERHUB_HOST`` is
       only set automatically in subdomain routing mode and must be supplied manually in path-based routing.
    3. ``CODESPACE_NAME``                                          — GitHub Codespaces port-forwarding URL.
    4. ``""``                                                      — local; callers fall back to ``http://localhost:{port}``.
    """
    if explicit := os.getenv("DATAVIZ_MCP_EXTERNAL_URL", ""):
        return explicit.rstrip("/")

    hub_host = os.getenv("JUPYTERHUB_HOST", "")
    hub_prefix = os.getenv("JUPYTERHUB_SERVICE_PREFIX", "")
    if hub_host and hub_prefix:
        if not hub_host.startswith(("http://", "https://")):
            hub_host = f"https://{hub_host}"
        return f"{hub_host.rstrip('/')}{hub_prefix}proxy/{port}"

    if codespace := os.getenv("CODESPACE_NAME", ""):
        domain = os.getenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN") or "app.github.dev"
        return f"https://{codespace}-{port}.{domain}"

    return ""


class Config(BaseModel):
    """DataViz MCP configuration."""

    port: int = Field(default=5077, description="Port for the Panel server")
    host: str = Field(default="localhost", description="Host address for the Panel server")
    max_restarts: int = Field(default=3, description="Maximum number of restart attempts")
    db_path: Path = Field(
        default_factory=lambda: _default_user_dir() / "snippets" / "snippets.db",
        description="Path to SQLite database for snippets",
    )
    external_url: str = Field(
        default="",
        description=(
            "Externally reachable base URL for the Panel server (port-inclusive). "
            "Auto-detected from JUPYTERHUB_HOST + JUPYTERHUB_SERVICE_PREFIX (JupyterHub) "
            "or CODESPACE_NAME (GitHub Codespaces) if not set explicitly via DATAVIZ_MCP_EXTERNAL_URL."
        ),
    )
    screenshot_width: int = Field(default=1200, description="Viewport width (px) for screenshot capture")
    screenshot_height: int = Field(default=800, description="Viewport height (px) for screenshot capture")
    screenshot_settle_ms: int = Field(default=1200, description="Delay (ms) after content mounts before capturing, to let Bokeh finish drawing")
    screenshot_timeout_ms: int = Field(default=30000, description="Max time (ms) to wait for the page to load before capturing")


_config: Config | None = None


def get_config() -> Config:
    """Get or create the config instance."""
    global _config
    if _config is None:
        port = default_panel_port()
        _config = Config(
            port=port,
            host=os.getenv("DATAVIZ_MCP_HOST", "localhost"),
            max_restarts=int(os.getenv("DATAVIZ_MCP_MAX_RESTARTS", "3")),
            db_path=Path(os.getenv("DATAVIZ_MCP_DB_PATH", str(_default_user_dir() / "snippets" / "snippets.db"))),
            external_url=_resolve_external_url(port),
            screenshot_width=int(os.getenv("DATAVIZ_MCP_SCREENSHOT_WIDTH", "1200")),
            screenshot_height=int(os.getenv("DATAVIZ_MCP_SCREENSHOT_HEIGHT", "800")),
            screenshot_settle_ms=int(os.getenv("DATAVIZ_MCP_SCREENSHOT_SETTLE_MS", "1200")),
            screenshot_timeout_ms=int(os.getenv("DATAVIZ_MCP_SCREENSHOT_TIMEOUT_MS", "30000")),
        )
    return _config


def reset_config() -> None:
    """Reset config (for testing)."""
    global _config
    _config = None
