"""REST API endpoints for the Display System.

This module implements Tornado RequestHandler classes that provide
HTTP endpoints for creating visualizations and checking server health.
"""

import base64
import contextlib
import io
import json
import logging
import sys
import traceback
from datetime import datetime
from datetime import timezone

from tornado.web import RequestHandler

from dataviz_mcp import diagnostics
from dataviz_mcp.config import get_config
from dataviz_mcp.database import get_db
from dataviz_mcp.utils import execute_in_module
from dataviz_mcp.utils import extract_last_expression
from dataviz_mcp.utils import validate_code
from dataviz_mcp.utils import validate_extension_availability
from dataviz_mcp.validation import SecurityError
from dataviz_mcp.validation import ast_check
from dataviz_mcp.validation import check_packages
from dataviz_mcp.validation import ruff_check

logger = logging.getLogger(__name__)


def _get_external_base_url(request_host: str) -> str | None:
    """Get external base URL for links returned to clients.

    Returns ``config.external_url`` when set (auto-detected from environment),
    otherwise ``None`` (caller should fall back to the request URL).
    """
    try:
        return get_config().external_url or None
    except Exception:
        return None


class SnippetEndpoint(RequestHandler):
    """Tornado RequestHandler for /api/snippet endpoint."""

    def post(self):
        """Handle POST requests to store snippets and create visualizations."""
        # Get database instance
        db = get_db()

        try:
            # Parse JSON body
            request_body = json.loads(self.request.body.decode("utf-8"))

            # Extract parameters
            code = request_body.get("code", "")
            name = request_body.get("name", "")
            description = request_body.get("description", "")
            method = request_body.get("method", "inline")
            validated = request_body.get("validated", False)
            draft_id = request_body.get("draft_id", "")

            if draft_id:
                snippet = db.promote_draft(draft_id)
            else:
                # Skip validation if already done by the MCP show tool.
                snippet = db.create_visualization(
                    app=code,
                    name=name,
                    description=description,
                    method=method,
                    skip_validation=validated,
                )

            if base_url := _get_external_base_url(self.request.host):
                url = f"{base_url}/view?id={snippet.id}"
            else:
                full_url = self.request.full_url()
                url = full_url.replace("/api/snippet", "/view?id=" + snippet.id)

            result = {
                "id": snippet.id,
                "url": url,
            }
            if snippet.error_message:
                result["error_message"] = snippet.error_message

            # Return success response
            self.set_status(200)
            self.set_header("Content-Type", "application/json")
            self.write(result)

        except SyntaxError as e:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "SyntaxError", "message": str(e)})
        except SecurityError as e:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "SecurityError", "message": str(e)})
        except ValueError as e:
            self.set_status(400)
            self.set_header("Content-Type", "application/json")
            self.write({"error": "ValueError", "message": str(e)})
        except Exception as e:
            # Handle all other errors
            logger.exception("Error in /api/snippet endpoint")
            self.set_status(500)
            self.set_header("Content-Type", "application/json")
            self.write(
                {
                    "error": "InternalError",
                    "message": str(e),
                    "traceback": traceback.format_exc(),
                }
            )


def _local_host(host: str) -> str:
    """Return a host usable for self-connections (the server screenshots itself)."""
    return "127.0.0.1" if host in ("0.0.0.0", "::", "") else host


class SnippetEditEndpoint(RequestHandler):
    """Replace one exact fragment of a snippet without resending all its code."""

    def _error(self, status: int, message: str, error: str | None = None) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.write({"error": error or message, "message": message})

    def post(self):
        """Validate and apply one unambiguous source replacement."""
        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except ValueError:
            self._error(400, "Request body must be JSON")
            return
        snippet_id = body.get("snippet_id", "")
        old_str = body.get("old_str", "")
        new_str = body.get("new_str", "")
        if not snippet_id:
            self._error(400, "Missing 'snippet_id' in request body")
            return
        if not old_str:
            self._error(400, "Missing 'old_str' in request body")
            return

        db = get_db()
        snippet = db.get_snippet(snippet_id)
        if snippet is None:
            self._error(404, f"No snippet found with id {snippet_id!r}")
            return
        matches = snippet.app.count(old_str)
        if matches == 0:
            self._error(400, "old_str was not found in the stored code. Match its text and indentation exactly.", error="NoMatch")
            return
        if matches > 1:
            self._error(400, f"old_str appears {matches} times. Include more surrounding text to make the edit unique.", error="AmbiguousMatch")
            return
        edited = snippet.app.replace(old_str, new_str, 1)
        try:
            if syntax_error := ast_check(edited):
                self._error(400, f"That edit would leave the code unparsable: {syntax_error}", error="SyntaxError")
                return
            ruff_check(edited)
            if package_error := check_packages(edited):
                self._error(400, package_error, error="PackageError")
                return
            if snippet.method == "server":
                validate_extension_availability(edited)
            if error := validate_code(edited):
                self._error(400, f"The edited code no longer runs: {error}", error="RuntimeError")
                return
        except SecurityError as e:
            self._error(400, str(e), error="SecurityError")
            return
        except Exception as e:
            self._error(400, f"The edited code could not be validated: {e}", error="ValidationError")
            return

        if snippet.draft:
            db.update_snippet(snippet.id, app=edited, status="success", error_message="")
            result_id, forked = snippet.id, False
        else:
            fork = db.create_visualization(
                app=edited,
                name=snippet.name,
                description=snippet.description,
                method=snippet.method,
                execute=False,
                format=False,
                draft=True,
            )
            db.update_snippet(fork.id, status="success")
            result_id, forked = fork.id, True
        self.set_header("Content-Type", "application/json")
        self.write({"id": result_id, "chars": len(edited), "forked": forked})


class ScreenshotEndpoint(RequestHandler):
    """Render a snippet's ``/view`` page via GET /api/screenshot?id=...

    Loads the live ``/view`` page in a headless browser (Playwright) and returns
    a PNG, giving LLMs a picture of the *rendered* output — layout, fonts, and
    margins as a user would see them. When no browser is installed/launchable
    this returns HTTP 503 with an install hint so the caller can surface a clear
    message instead of failing opaquely.

    Query parameters
    ----------------
    id : str
        Snippet id to render (required).
    width, height : int
        Viewport size in px (default from config).
    full_page : bool
        Capture the full scrollable page rather than just the viewport.
    """

    def _error(self, status: int, message: str, error: str | None = None) -> None:
        self.set_status(status)
        self.set_header("Content-Type", "application/json")
        self.write({"error": error or message, "message": message})

    async def get(self):
        """Capture and return the snippet identified by ``?id=``."""
        from dataviz_mcp import screenshot

        snippet_id = self.get_argument("id", "")
        if not snippet_id:
            self._error(400, "Missing 'id' parameter")
            return

        db = get_db()
        snippet = db.get_snippet(snippet_id)
        if not snippet:
            self._error(404, f"Snippet {snippet_id} not found")
            return

        config = get_config()
        try:
            width = int(self.get_argument("width", str(config.screenshot_width)))
            height = int(self.get_argument("height", str(config.screenshot_height)))
        except ValueError:
            self._error(400, "width and height must be integers")
            return
        full_page = self.get_argument("full_page", "false").lower() in ("1", "true", "yes")
        raw_do = self.get_argument("do", "")
        try:
            do = json.loads(raw_do) if raw_do else None
        except ValueError:
            self._error(400, 'do must be JSON-encoded, e.g. do=[{"click": "Reports"}]', error="ActionError")
            return

        view_url = f"http://{_local_host(config.host)}:{config.port}/view?id={snippet_id}"

        try:
            console_lines: list[str] = []
            capture = await screenshot.capture_pages(
                view_url,
                width=width,
                height=height,
                full_page=full_page,
                settle_ms=config.screenshot_settle_ms,
                timeout_ms=config.screenshot_timeout_ms,
                do=do,
                max_tiles=config.screenshot_max_tiles,
                max_actions=config.screenshot_max_actions,
                console_sink=console_lines,
            )
        except screenshot.PlaywrightUnavailableError as e:
            self._error(503, str(e), error="PlaywrightUnavailable")
            return
        except screenshot.ActionError as e:
            self._error(400, str(e), error="ActionError")
            return
        except Exception as e:
            logger.exception(f"Error capturing screenshot for snippet {snippet_id}")
            self.set_status(500)
            self.set_header("Content-Type", "application/json")
            self.write({"error": str(e), "traceback": traceback.format_exc()})
            return

        payload = diagnostics.build(diagnostics.pop(snippet_id), console_lines)
        self._write_capture(capture, diagnostics.encode(payload) if payload else "")

    async def post(self):
        """Render submitted code privately and return its screenshot plus draft id."""
        from dataviz_mcp import screenshot

        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except ValueError:
            self._error(400, "Request body must be JSON")
            return
        code = body.get("code", "")
        if not code:
            self._error(400, "Missing 'code' in request body")
            return

        db = get_db()
        try:
            db.delete_stale_drafts(get_config().draft_retention_hours)
            draft = db.create_visualization(
                app=code,
                name=body.get("name", ""),
                description=body.get("description", ""),
                method=body.get("method", "inline"),
                execute=False,
                format=False,
                draft=True,
            )
        except SyntaxError as e:
            self._error(400, str(e), error="SyntaxError")
            return
        except SecurityError as e:
            self._error(400, str(e), error="SecurityError")
            return
        except ValueError as e:
            self._error(400, str(e), error="ValueError")
            return

        config = get_config()
        try:
            width = int(body.get("width") or config.screenshot_width)
            height = int(body.get("height") or config.screenshot_height)
        except (TypeError, ValueError):
            db.delete_snippet(draft.id)
            self._error(400, "width and height must be integers")
            return
        view_url = f"http://{_local_host(config.host)}:{config.port}/view?id={draft.id}"
        console_lines: list[str] = []
        try:
            capture = await screenshot.capture_pages(
                view_url,
                width=width,
                height=height,
                full_page=bool(body.get("full_page", False)),
                settle_ms=config.screenshot_settle_ms,
                timeout_ms=config.screenshot_timeout_ms,
                do=body.get("do"),
                max_tiles=config.screenshot_max_tiles,
                max_actions=config.screenshot_max_actions,
                console_sink=console_lines,
            )
        except screenshot.PlaywrightUnavailableError as e:
            db.delete_snippet(draft.id)
            self._error(503, str(e), error="PlaywrightUnavailable")
            return
        except screenshot.ActionError as e:
            db.delete_snippet(draft.id)
            self._error(400, str(e), error="ActionError")
            return
        except Exception as e:
            logger.exception("Error capturing private draft %s", draft.id)
            db.delete_snippet(draft.id)
            self._error(500, str(e), error="InternalError")
            return

        rendered = db.get_snippet(draft.id)
        if rendered is not None and rendered.status == "error":
            db.delete_snippet(draft.id)
            self._error(400, rendered.error_message or "The draft failed to render.", error="RuntimeError")
            return
        payload = diagnostics.build(diagnostics.pop(draft.id), console_lines)
        self.set_header(diagnostics.DRAFT_ID_HEADER, draft.id)
        self._write_capture(capture, diagnostics.encode(payload) if payload else "")

    def _write_capture(self, capture, diagnostics_header: str) -> None:
        """Write one PNG or a JSON tile list, plus screenshot metadata headers."""
        from dataviz_mcp import screenshot

        if diagnostics_header:
            self.set_header(diagnostics.HEADER, diagnostics_header)
        self.set_header(screenshot.META_HEADER, screenshot.encode_meta(capture))
        self.set_status(200)
        if len(capture.images) > 1:
            self.set_header("Content-Type", "application/json")
            self.write({"images": [{"label": label, "png": base64.b64encode(png).decode("ascii")} for label, png in capture.images]})
        else:
            self.set_header("Content-Type", "image/png")
            self.write(capture.png or b"")


class EvaluateEndpoint(RequestHandler):
    """Execute code for textual inspection without creating a visualization."""

    def post(self):
        """Run the posted code and return stdout, final expression, or error JSON."""
        try:
            body = json.loads(self.request.body.decode("utf-8"))
        except ValueError:
            self.set_status(400)
            self.write({"error": "ValueError", "message": "Request body must be JSON"})
            return
        code = body.get("code", "")
        if not code:
            self.set_status(400)
            self.write({"error": "ValueError", "message": "Missing 'code' in request body"})
            return
        if syntax_error := ast_check(code):
            self.set_status(400)
            self.write({"error": "SyntaxError", "message": syntax_error})
            return

        output = io.StringIO()
        result = ""
        error = ""
        trace = ""
        module_name = f"dataviz_eval_{abs(hash(code)) % (10**10)}"
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                statements, expression = extract_last_expression(code)
                try:
                    namespace = execute_in_module(statements, module_name=module_name, cleanup=False)
                    if expression and (value := eval(expression, namespace)) is not None:  # noqa: S307
                        result = repr(value)
                finally:
                    sys.modules.pop(module_name, None)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            trace = traceback.format_exc()
        self.set_header("Content-Type", "application/json")
        self.write(
            {
                "stdout": diagnostics.truncate(output.getvalue()),
                "result": diagnostics.truncate(result),
                "error": error,
                "traceback": diagnostics.truncate(trace),
            }
        )


class HealthEndpoint(RequestHandler):
    """Tornado RequestHandler for /api/health endpoint."""

    def get(self):
        """Handle GET requests to check server health.

        The payload reports the interpreter running this server (``sys.prefix``
        and ``sys.executable``) so a manager can tell whether a server already
        listening on the port belongs to its own environment before adopting it.
        """
        self.set_status(200)
        self.set_header("Content-Type", "application/json")
        self.write(
            {
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "prefix": sys.prefix,
                "executable": sys.executable,
            }
        )
