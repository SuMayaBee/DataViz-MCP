"""Headless-browser screenshot capture for rendered Panel snippets."""

import asyncio
import base64
import json
import logging
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from dataclasses import field

from dataviz_mcp.config import get_config

logger = logging.getLogger(__name__)


class PlaywrightUnavailableError(RuntimeError):
    """Raised when Playwright or its browser is not installed or launchable."""


class ActionError(ValueError):
    """Raised when a requested browser action cannot be carried out."""


_INSTALL_HINT = "Playwright's Chromium browser is not installed. Run:\n    pls install-browser"
_CONTENT_SELECTOR = "canvas, .bk-Row, .bk-Column, .bk, .markdown, table, img, svg"
_CONTROL_SELECTOR = (
    "button, a[href], select, summary, input:not([type='hidden']), [title], .bk-tab, "
    "[role=tab], [role=button], [role=menuitem], [role=option], [role=switch], [role=slider]"
)
_CONTROL_NAME_JS = """el => (
    (el.labels && el.labels[0] && el.labels[0].textContent.trim())
    || el.getAttribute('aria-label')
    || (el.innerText || el.textContent || '').trim()
    || el.getAttribute('title')
    || el.getAttribute('placeholder')
    || ''
).trim()"""
_SCROLLER_JS = """() => {
    const root = document.scrollingElement || document.documentElement;
    let best = root;
    let hidden = root.scrollHeight - root.clientHeight;
    const visit = (node) => {
        for (const el of node.querySelectorAll('*')) {
            const overflowY = getComputedStyle(el).overflowY;
            if (overflowY === 'auto' || overflowY === 'scroll') {
                const overflow = el.scrollHeight - el.clientHeight;
                if (overflow > hidden) { best = el; hidden = overflow; }
            }
            if (el.shadowRoot) visit(el.shadowRoot);
        }
    };
    visit(document);
    return best;
}"""
_SCROLLER_METRICS_JS = "el => ({content: el.scrollHeight, visible: el.clientHeight, offset: el.scrollTop})"
_SCROLL_TO_JS = "(el, offset) => { el.scrollTop = offset; }"
_MAX_ACTIONS = 20
_MAX_CONTROLS_REPORTED = 24
_DRAG_STEPS = 12
_TILE_SETTLE_MS = 250
META_HEADER = "X-DataViz-Capture"
_MAX_META_BYTES = 4096
_MAX_LABEL_CHARS = 80


def install_browser() -> int:
    """Download the Chromium browser used by the screenshot tool."""
    return subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"]).returncode


def is_browser_installed() -> bool:
    """Return whether Playwright's Chromium binary is installed."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            return bool(p.chromium.executable_path) and os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


@dataclass
class Capture:
    """Images taken during a browser visit and an account of omitted content."""

    images: list[tuple[str, bytes]] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    total_tiles: int = 1
    captured_tiles: int = 1

    @property
    def png(self) -> bytes | None:
        """Return the first image, for consumers that need only one."""
        return self.images[0][1] if self.images else None


def encode_meta(capture: Capture) -> str:
    """Encode bounded capture metadata for an HTTP header."""
    labels = [label[:_MAX_LABEL_CHARS] for label in capture.controls]
    while True:
        payload = {"controls": labels, "total_tiles": capture.total_tiles, "captured_tiles": capture.captured_tiles}
        encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
        if len(encoded) <= _MAX_META_BYTES or not labels:
            return encoded
        labels.pop()


def decode_meta(raw: str) -> dict:
    """Decode capture metadata, returning an empty mapping for malformed input."""
    if not raw:
        return {}
    try:
        decoded = json.loads(base64.b64decode(raw.encode("ascii")).decode("utf-8"))
    except Exception:
        logger.debug("Could not decode %s header", META_HEADER, exc_info=True)
        return {}
    return decoded if isinstance(decoded, dict) else {}


def apply_meta(capture: Capture, meta: dict) -> Capture:
    """Apply decoded HTTP metadata to a capture."""
    controls = meta.get("controls")
    capture.controls = [str(label) for label in controls] if isinstance(controls, list) else []
    try:
        capture.total_tiles = max(1, int(meta.get("total_tiles", 1)))
        capture.captured_tiles = max(1, int(meta.get("captured_tiles", 1)))
    except (TypeError, ValueError):
        capture.total_tiles = capture.captured_tiles = 1
    return capture


def tile_label(index: int, total: int) -> str:
    """Return a reader-friendly label for a tile."""
    return f"screen {index + 1} of {total}" if total > 1 else ""


_ACTION_SHAPES = {
    "click": '{"click": "<name>"}, optionally with "nth": <int>',
    "select": '{"select": "<name>", "value": "<option>"}',
    "fill": '{"fill": "<name>", "value": "<text>"}',
    "key": '{"key": "<KeyName>"}, e.g. "Enter" or "ArrowRight"',
    "drag": '{"drag": [x0, y0, x1, y1]} in viewport pixels',
    "wait": '{"wait": <milliseconds>}',
}


def _shapes_hint() -> str:
    return "Valid steps are: " + "; ".join(_ACTION_SHAPES.values()) + "."


def check_actions(do: list | None, limit: int = _MAX_ACTIONS) -> list[dict]:
    """Validate a list of browser actions before loading a page."""
    if not do:
        return []
    if not isinstance(do, list):
        raise ActionError(f"'do' must be a list of steps, not {type(do).__name__}. {_shapes_hint()}")
    if len(do) > limit:
        raise ActionError(f"'do' has {len(do)} steps; at most {limit} are run in one capture. Split the work across calls.")
    checked: list[dict] = []
    for position, step in enumerate(do, start=1):
        if not isinstance(step, dict):
            raise ActionError(f"Step {position} must be an object, not {type(step).__name__}. {_shapes_hint()}")
        verbs = [key for key in step if key in _ACTION_SHAPES]
        if not verbs:
            unknown = ", ".join(repr(key) for key in step) or "nothing"
            raise ActionError(f"Step {position} names no action ({unknown} given). {_shapes_hint()}")
        if len(verbs) > 1:
            raise ActionError(f"Step {position} names {len(verbs)} actions ({', '.join(verbs)}); each step does exactly one thing.")
        verb = verbs[0]
        value = step[verb]
        if verb in ("click", "select", "fill"):
            if not isinstance(value, str) or not value.strip():
                raise ActionError(f"Step {position} ({verb}) needs a non-empty name to act on. Expected {_ACTION_SHAPES[verb]}.")
            if verb in ("select", "fill") and not isinstance(step.get("value"), str):
                raise ActionError(f"Step {position} ({verb}) needs a string 'value'. Expected {_ACTION_SHAPES[verb]}.")
            if verb == "click" and "nth" in step and not isinstance(step["nth"], int):
                raise ActionError(f"Step {position} ({verb}) has a non-integer 'nth'. Expected {_ACTION_SHAPES[verb]}.")
        elif verb == "key" and (not isinstance(value, str) or not value.strip()):
            raise ActionError(f"Step {position} ({verb}) needs a key name. Expected {_ACTION_SHAPES[verb]}.")
        elif verb == "drag" and (
            not isinstance(value, (list, tuple)) or len(value) != 4 or not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in value)
        ):
            raise ActionError(f"Step {position} ({verb}) needs exactly four numbers. Expected {_ACTION_SHAPES[verb]}.")
        elif verb == "wait" and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
            raise ActionError(f"Step {position} ({verb}) needs a non-negative number of milliseconds. Expected {_ACTION_SHAPES[verb]}.")
        checked.append(step)
    return checked


class _BrowserManager:
    """Lazily launch and reuse one headless Chromium browser."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def _ensure_browser(self):
        if self._browser is not None and self._browser.is_connected():
            return self._browser
        async with self._lock:
            if self._browser is not None and self._browser.is_connected():
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except ImportError as e:
                raise PlaywrightUnavailableError(_INSTALL_HINT) from e
            self._playwright = await async_playwright().start()
            try:
                self._browser = await self._playwright.chromium.launch(headless=True)
            except Exception as e:
                await self._stop_playwright()
                raise PlaywrightUnavailableError(f"Failed to launch Chromium: {e}\n{_INSTALL_HINT}") from e
            return self._browser

    async def capture(
        self,
        url: str,
        *,
        width: int,
        height: int,
        full_page: bool,
        settle_ms: int,
        timeout_ms: int,
        do: list | None = None,
        max_tiles: int = 4,
        max_actions: int = _MAX_ACTIONS,
        console_sink: list[str] | None = None,
    ) -> Capture:
        """Load a page, optionally interact with it, and capture readable tiles."""
        steps = check_actions(do, max_actions)
        browser = await self._ensure_browser()
        context = await browser.new_context(viewport={"width": width, "height": height})
        try:
            page = await context.new_page()
            if console_sink is not None:
                max_lines = get_config().diagnostics_max_console_lines

                def note(text: str) -> None:
                    if len(console_sink) < max_lines:
                        console_sink.append(text)

                page.on("console", lambda msg: note(f"[{msg.type}] {msg.text}"))
                page.on("pageerror", lambda error: note(f"[pageerror] {error}"))
            await page.goto(url, wait_until="load", timeout=timeout_ms)
            try:
                await page.wait_for_selector(_CONTENT_SELECTOR, timeout=min(5000, timeout_ms))
            except Exception:
                logger.debug("No known content selector matched for %s; capturing anyway.", url)
            await page.wait_for_timeout(settle_ms)
            for step in steps:
                await self._perform(page, step)
                await page.wait_for_timeout(settle_ms)
            shots, total = await self._shoot(page, max_tiles=max_tiles if full_page else 1)
            return Capture(
                images=[(tile_label(index, len(shots)), png) for index, png in enumerate(shots)],
                controls=await self._controls(page),
                total_tiles=total,
                captured_tiles=len(shots),
            )
        finally:
            await context.close()

    async def _controls(self, page) -> list[str]:
        try:
            handles = await page.locator(_CONTROL_SELECTOR).all()
        except Exception:
            logger.debug("Could not enumerate controls.", exc_info=True)
            return []
        names: list[str] = []
        seen: set[str] = set()
        for handle in handles:
            if len(names) >= _MAX_CONTROLS_REPORTED:
                break
            try:
                name = (await handle.evaluate(_CONTROL_NAME_JS)).strip()
            except Exception:
                continue
            if name and name not in seen:
                names.append(name)
                seen.add(name)
        return names

    async def _locate(self, page, name: str, nth: int | None, tag: str | None = None):
        def scoped(locator):
            return locator.and_(page.locator(tag)) if tag else locator

        exact = scoped(
            page.get_by_text(name, exact=True)
            .or_(page.get_by_title(name, exact=True))
            .or_(page.get_by_label(name, exact=True))
            .or_(page.get_by_placeholder(name, exact=True))
        )
        candidates = exact if await exact.count() else scoped(
            page.get_by_text(name)
            .or_(page.get_by_title(name))
            .or_(page.get_by_label(name))
            .or_(page.get_by_placeholder(name))
        )
        count = await candidates.count()
        if count == 0:
            controls = await self._controls(page)
            available = ", ".join(controls) if controls else "nothing clickable was found on the page"
            raise ActionError(f"No element matches {name!r}. On this page: {available}.")
        if nth is not None:
            if not 0 <= nth < count:
                raise ActionError(f"{name!r} matches {count} elements; 'nth' must be between 0 and {count - 1}.")
            return candidates.nth(nth)
        if count > 1:
            raise ActionError(f'{name!r} matches {count} elements. Use a more specific name, or add "nth": 0..{count - 1} to pick one.')
        return candidates.first

    async def _perform(self, page, step: dict) -> None:
        if "click" in step:
            await (await self._locate(page, step["click"], step.get("nth"))).click()
        elif "select" in step:
            await (await self._locate(page, step["select"], None, tag="select")).select_option(label=step["value"])
        elif "fill" in step:
            await (await self._locate(page, step["fill"], None, tag="input, textarea")).fill(step["value"])
        elif "key" in step:
            await page.keyboard.press(step["key"])
        elif "drag" in step:
            x0, y0, x1, y1 = step["drag"]
            await page.mouse.move(x0, y0)
            await page.mouse.down()
            await page.mouse.move(x1, y1, steps=_DRAG_STEPS)
            await page.mouse.up()
        elif "wait" in step:
            await page.wait_for_timeout(step["wait"])

    async def _shoot(self, page, *, max_tiles: int) -> tuple[list[bytes], int]:
        scroller = await page.evaluate_handle(_SCROLLER_JS)
        try:
            metrics = await scroller.evaluate(_SCROLLER_METRICS_JS)
            step = max(1, int(metrics["visible"]))
            total = max(1, math.ceil(int(metrics["content"]) / step))
            if total == 1 or max_tiles <= 1:
                return [await page.screenshot(type="png")], total
            shots = []
            for index in range(min(total, max_tiles)):
                await scroller.evaluate(_SCROLL_TO_JS, index * step)
                await page.wait_for_timeout(_TILE_SETTLE_MS)
                shots.append(await page.screenshot(type="png"))
            await scroller.evaluate(_SCROLL_TO_JS, metrics["offset"])
            return shots, total
        finally:
            await scroller.dispose()

    async def _stop_playwright(self) -> None:
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


_manager = _BrowserManager()


async def capture_pages(
    url: str,
    *,
    width: int = 1200,
    height: int = 800,
    full_page: bool = False,
    settle_ms: int = 1200,
    timeout_ms: int = 30000,
    do: list | None = None,
    max_tiles: int = 4,
    max_actions: int = _MAX_ACTIONS,
    console_sink: list[str] | None = None,
) -> Capture:
    """Capture a page, returning one or more viewport-sized PNGs and metadata."""
    return await _manager.capture(
        url,
        width=width,
        height=height,
        full_page=full_page,
        settle_ms=settle_ms,
        timeout_ms=timeout_ms,
        do=do,
        max_tiles=max_tiles,
        max_actions=max_actions,
        console_sink=console_sink,
    )


async def capture_png(url: str, **kwargs) -> bytes | None:
    """Capture the first PNG of a page for backward-compatible callers."""
    return (await capture_pages(url, **kwargs)).png
