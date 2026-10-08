"""Collect render diagnostics for the MCP screenshot tool."""

from __future__ import annotations

import base64
import json
import logging
from collections import OrderedDict
from threading import Lock

from dataviz_mcp.config import get_config

logger = logging.getLogger(__name__)

HEADER = "X-DataViz-Diagnostics"
DRAFT_ID_HEADER = "X-DataViz-Draft-Id"
MAX_ENTRIES = 64

_store: OrderedDict[str, str] = OrderedDict()
_lock = Lock()


def record(snippet_id: str, text: str) -> None:
    """Store stdout or stderr produced while rendering a snippet."""
    if not snippet_id or not text or not text.strip():
        return
    max_chars = get_config().diagnostics_max_chars
    with _lock:
        _store[snippet_id] = (_store.get(snippet_id, "") + text)[-(max_chars * 2) :]
        _store.move_to_end(snippet_id)
        while len(_store) > MAX_ENTRIES:
            _store.popitem(last=False)


def pop(snippet_id: str) -> str:
    """Return and remove the output recorded for a snippet."""
    with _lock:
        return _store.pop(snippet_id, "")


def truncate(text: str, limit: int | None = None) -> str:
    """Clip text while keeping its useful final lines."""
    if limit is None:
        limit = get_config().diagnostics_max_chars
    if len(text) <= limit:
        return text
    return f"[… {len(text) - limit} earlier characters omitted]\n{text[-limit:]}"


def collapse_repeats(lines: list[str]) -> list[str]:
    """Collapse repeated adjacent browser-console messages."""
    collapsed: list[list[str | int]] = []
    for line in lines:
        if collapsed and collapsed[-1][0] == line:
            collapsed[-1][1] = int(collapsed[-1][1]) + 1
        else:
            collapsed.append([line, 1])
    return [str(text) if count == 1 else f"{text}  (x{count})" for text, count in collapsed]


def build(python_output: str, console_lines: list[str] | None) -> dict[str, str]:
    """Assemble the non-empty diagnostic streams for transport."""
    payload: dict[str, str] = {}
    if python_output and python_output.strip():
        payload["python"] = truncate(python_output.strip())
    if console_lines:
        console = "\n".join(collapse_repeats(console_lines)).strip()
        if console:
            payload["console"] = truncate(console)
    return payload


def encode(payload: dict[str, str]) -> str:
    """Encode diagnostics safely for an HTTP response header."""
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def decode(raw: str) -> dict[str, str]:
    """Decode a diagnostics header, degrading safely on malformed input."""
    if not raw:
        return {}
    try:
        payload = json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception:
        logger.debug("Could not decode diagnostics header", exc_info=True)
        return {}
    return payload if isinstance(payload, dict) else {}


def render(payload: dict[str, str]) -> str:
    """Format diagnostics as text returned beside a screenshot."""
    sections = []
    if payload.get("python"):
        sections.append(f"stdout/stderr from the snippet:\n{payload['python']}")
    if payload.get("console"):
        sections.append(f"browser console:\n{payload['console']}")
    return "\n\n".join(sections)
