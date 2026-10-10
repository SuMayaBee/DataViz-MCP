"""Tests for automatic data loading and visualization selection."""

import json

import pandas as pd
import pytest

import dataviz_mcp.server as server_module
from dataviz_mcp.data_loader import build_visualization_code
from dataviz_mcp.data_loader import inspect_dataframe
from dataviz_mcp.data_loader import load_dataframe
from dataviz_mcp.data_loader import profile_dataframe


def test_load_local_csv(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text("month,sales\nJan,10\nFeb,14\n", encoding="utf-8")

    frame, source_kind = load_dataframe(str(path))

    assert source_kind == "local"
    assert frame.to_dict("records") == [{"month": "Jan", "sales": 10}, {"month": "Feb", "sales": 14}]


@pytest.mark.parametrize(
    ("frame", "source_kind", "threshold", "category", "strategy"),
    [
        (pd.DataFrame({"x": [1], "y": [2]}), "local", 100, "simple_data", "hvplot"),
        (pd.DataFrame({"x": [1], "y": [2], "z": [3]}), "local", 100, "multidimensional_data", "holoviews"),
        (pd.DataFrame({"x": range(5), "y": range(5)}), "local", 5, "big_data", "datashader"),
        (pd.DataFrame({"x": range(5), "y": range(5), "z": range(5)}), "remote", 5, "remote_data", "hvplot"),
    ],
)
def test_profile_selects_expected_strategy(frame, source_kind, threshold, category, strategy):
    profile = profile_dataframe(frame, source_kind, threshold)

    assert profile.category == category
    assert profile.strategy == strategy


def test_big_data_code_enables_datashader(tmp_path):
    path = tmp_path / "large.csv"
    frame = pd.DataFrame({"x": range(5), "y": range(5)})
    profile = profile_dataframe(frame, "local", big_data_rows=5)

    code = build_visualization_code(str(path), frame, profile, "Large data")

    assert "import datashader" in code
    assert "rasterize=True" in code
    assert "dynspread=True" in code


def test_multidimensional_code_uses_holoviews(tmp_path):
    path = tmp_path / "dimensions.csv"
    frame = pd.DataFrame({"x": [1], "y": [2], "z": [3]})
    profile = profile_dataframe(frame, "local")

    code = build_visualization_code(str(path), frame, profile, "Dimensions")

    assert "import holoviews as hv" in code
    assert "hv.Scatter" in code
    assert "color = 'z'" in code


def test_inspection_reports_quality_statistics_and_recommendations():
    frame = pd.DataFrame({"month": ["Jan", "Feb", "Feb"], "sales": [10.0, None, 12.0]})
    profile = profile_dataframe(frame, "local")

    analysis = inspect_dataframe(frame, profile)

    assert analysis["shape"] == {"rows": 3, "columns": 2}
    assert analysis["missing_values"] == 1
    assert analysis["duplicate_rows"] == 0
    assert len(analysis["preview"]) == 3
    assert {item["type"] for item in analysis["recommendations"]} >= {"Line chart", "Bar chart", "Histogram"}


@pytest.mark.parametrize(
    ("frame", "threshold", "strategy"),
    [
        (pd.DataFrame({"category": ["A", "B"], "value": [3, 7]}), 100, "hvplot"),
        (pd.DataFrame({"x": [1, 2], "y": [2, 4], "z": [3, 6]}), 100, "holoviews"),
        (pd.DataFrame({"x": range(5), "y": range(5)}), 5, "datashader"),
    ],
)
def test_generated_visualization_code_executes(tmp_path, frame, threshold, strategy):
    path = tmp_path / "data.csv"
    frame.to_csv(path, index=False)
    profile = profile_dataframe(frame, "local", big_data_rows=threshold)
    namespace: dict = {}

    exec(build_visualization_code(str(path), frame, profile, "Test data"), namespace)  # noqa: S102

    assert profile.strategy == strategy
    assert namespace["plot"] is not None


@pytest.mark.asyncio
async def test_load_data_returns_profile_with_render_payload(monkeypatch):
    frame = pd.DataFrame({"category": ["A", "B"], "value": [3, 7]})
    monkeypatch.setattr(server_module, "load_dataframe", lambda source: (frame, "local"))

    async def fake_show(**kwargs):
        assert "hvplot.bar" in kwargs["code"]
        return json.dumps({"tool": "show", "status": "success", "url": "http://localhost/view?id=1", "tokens": 1})

    monkeypatch.setattr(server_module, "show", fake_show)

    payload = json.loads(await server_module.load_data("sales.csv", name="Sales"))

    assert payload["tool"] == "load_data"
    assert payload["visualized"] is True
    assert payload["data_profile"]["category"] == "simple_data"
    assert payload["data_profile"]["strategy"] == "hvplot"
    assert payload["url"].endswith("id=1")


@pytest.mark.asyncio
async def test_load_data_inspection_mode_does_not_render(monkeypatch):
    frame = pd.DataFrame({"category": ["A", "B"], "value": [3, 7]})
    monkeypatch.setattr(server_module, "load_dataframe", lambda source: (frame, "local"))

    async def forbidden_show(**kwargs):
        pytest.fail("show must not be called in inspection mode")

    monkeypatch.setattr(server_module, "show", forbidden_show)

    payload = json.loads(await server_module.load_data("sales.csv", visualize=False))

    assert payload["status"] == "success"
    assert payload["visualized"] is False
    assert "url" not in payload
    assert payload["analysis"]["shape"] == {"rows": 2, "columns": 2}
    assert payload["analysis"]["recommendations"]
