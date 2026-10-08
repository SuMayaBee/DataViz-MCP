"""Optional user instructions layered onto the built-in MCP prompts."""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_VAR = "DATAVIZ_MCP_PROMPTS_FILE"
_HEADER = "USER CONFIGURATION: Follow these rules before the built-in guidance below."


def _overrides() -> dict[str, str]:
    """Read a JSON prompt override file without making server startup fragile."""
    raw = os.getenv(ENV_VAR, "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(Path(raw).expanduser().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, str)}
    except Exception as exc:
        logger.warning("Could not load prompt overrides from %s: %s", raw, exc)
        return {}


def render(default: str, section: str) -> str:
    """Prepend the named user rule to a built-in prompt section, if configured."""
    rule = _overrides().get(section, "").strip()
    return f"{_HEADER}\n{rule}\n\n{default}" if rule else default
