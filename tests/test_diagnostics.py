"""Tests for diagnostics returned with rendered screenshots."""

from dataviz_mcp import diagnostics
from dataviz_mcp.config import get_config
from dataviz_mcp.config import reset_config


class TestDiagnostics:
    def setup_method(self) -> None:
        diagnostics._store.clear()

    def teardown_method(self) -> None:
        reset_config()

    def test_record_appends_and_pop_consumes(self) -> None:
        diagnostics.record("snippet", "first\n")
        diagnostics.record("snippet", "second\n")
        assert diagnostics.pop("snippet") == "first\nsecond\n"
        assert diagnostics.pop("snippet") == ""

    def test_blank_output_is_ignored(self) -> None:
        diagnostics.record("snippet", " \n")
        diagnostics.record("", "orphan")
        assert diagnostics.pop("snippet") == ""

    def test_store_is_bounded(self) -> None:
        for index in range(diagnostics.MAX_ENTRIES + 1):
            diagnostics.record(str(index), "x")
        assert len(diagnostics._store) == diagnostics.MAX_ENTRIES
        assert diagnostics.pop("0") == ""

    def test_truncate_keeps_tail(self) -> None:
        clipped = diagnostics.truncate("x" * 100, limit=10)
        assert clipped.endswith("x" * 10)
        assert "earlier characters omitted" in clipped

    def test_console_repeats_are_collapsed(self) -> None:
        assert diagnostics.collapse_repeats(["error", "error", "warning"]) == ["error  (x2)", "warning"]

    def test_transport_round_trip(self) -> None:
        payload = diagnostics.build("value: 42\n", ["[error] boom"])
        assert diagnostics.decode(diagnostics.encode(payload)) == payload

    def test_bad_header_is_ignored(self) -> None:
        assert diagnostics.decode("not-base64") == {}

    def test_render_labels_streams(self) -> None:
        text = diagnostics.render(diagnostics.build("out", ["[warning] browser"]))
        assert "stdout/stderr from the snippet:" in text
        assert "browser console:" in text

    def test_config_limits_respect_environment(self, monkeypatch) -> None:
        monkeypatch.setenv("DATAVIZ_MCP_DIAGNOSTICS_MAX_CHARS", "77")
        monkeypatch.setenv("DATAVIZ_MCP_DIAGNOSTICS_MAX_CONSOLE_LINES", "9")
        reset_config()
        assert get_config().diagnostics_max_chars == 77
        assert get_config().diagnostics_max_console_lines == 9
