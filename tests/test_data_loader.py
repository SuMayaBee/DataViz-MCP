"""Tests for automatic data loading and visualization selection."""

import json

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import dataviz_mcp.server as server_module
from dataviz_mcp.data_loader import SourceMetadata
from dataviz_mcp.data_loader import build_visualization_code
from dataviz_mcp.data_loader import inspect_dataframe
from dataviz_mcp.data_loader import load_dataframe
from dataviz_mcp.data_loader import load_dataset
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
        (pd.DataFrame({"x": range(5), "y": range(5), "z": range(5)}), "remote", 5, "big_data", "datashader"),
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


def test_big_data_axes_ignore_exported_index_constants_and_identifiers(tmp_path):
    path = tmp_path / "flights.csv"
    frame = pd.DataFrame(
        {
            "Unnamed: 0": range(10),
            "year": [2013] * 10,
            "flight": range(100, 110),
            "dep_delay": [2, 4, -1, 8, 0, 3, 7, 1, 5, 6],
            "arr_delay": [11, 5, -4, 13, -2, 4, 9, 0, 7, 8],
            "distance": [1400, 900, 300, 500, 700, 800, 1200, 400, 600, 1000],
        }
    )
    frame.to_csv(path, index=False)
    profile = profile_dataframe(frame, "local", big_data_rows=5)

    code = build_visualization_code(str(path), frame, profile, "NYC flights")

    assert "x = 'dep_delay'" in code
    assert "y = 'arr_delay'" in code
    assert "rasterize=True" in code
    assert "x = 'Unnamed: 0'" not in code
    assert "y = 'year'" not in code


def test_large_csv_is_counted_before_loading_and_profiled_from_sample(tmp_path):
    path = tmp_path / "large.csv"
    pd.DataFrame({"x": range(10_050), "y": range(10_050)}).to_csv(path, index=False)

    frame, metadata = load_dataset(str(path), big_data_rows=10_000)
    profile = profile_dataframe(frame, metadata.source_kind, 10_000, metadata)

    assert metadata.estimated_rows == 10_050
    assert metadata.row_count_exact is True
    assert metadata.profile_mode == "sampled"
    assert metadata.loaded_rows == 10_000
    assert len(frame) == 10_000
    assert profile.rows == 10_050
    assert profile.source_kind == "local"
    assert profile.category == "big_data"
    assert profile.strategy == "datashader"


def test_remote_source_is_separate_from_structural_category():
    frame = pd.DataFrame({"x": [1, 2], "y": [2, 3], "z": [3, 4]})
    metadata = SourceMetadata(
        source_kind="remote",
        format="csv",
        size_bytes=100,
        estimated_rows=2,
        row_count_exact=True,
        estimated_memory_bytes=200,
        profile_mode="complete",
        loaded_rows=2,
    )

    profile = profile_dataframe(frame, "remote", metadata=metadata)

    assert profile.source_kind == "remote"
    assert profile.category == "multidimensional_data"
    assert "multidimensional" in profile.traits


def test_netcdf_uses_dimensions_and_variable_metadata(tmp_path):
    path = tmp_path / "temperature.nc"
    dataset = xr.Dataset(
        {"temperature": (("time", "latitude", "longitude"), np.arange(24).reshape(2, 3, 4))},
        coords={"time": [0, 1], "latitude": [10, 20, 30], "longitude": [40, 50, 60, 70]},
    )
    dataset.to_netcdf(path)

    frame, metadata = load_dataset(str(path))
    profile = profile_dataframe(frame, metadata.source_kind, metadata=metadata)

    assert metadata.estimated_rows == 24
    assert metadata.dimensions == ("time", "latitude", "longitude")
    assert metadata.selected_variable == "temperature"
    assert profile.category == "multidimensional_data"
    assert profile.strategy == "holoviews"
    assert profile.format == "netcdf"
    assert {"labeled_array", "multidimensional"} <= set(profile.traits)
    assert list(frame.columns) == ["time", "latitude", "longitude", "temperature"]

    code = build_visualization_code(str(path), frame, profile, "Temperature")
    assert "x = 'longitude'" in code
    assert "y = 'latitude'" in code
    assert "color = 'temperature'" in code
    namespace: dict = {}
    exec(code, namespace)  # noqa: S102
    assert namespace["plot"] is not None


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


def test_inspection_bounds_wide_profiles_and_long_preview_values():
    frame = pd.DataFrame({f"column_{index}": [index] for index in range(120)})
    frame["column_0"] = ["x" * 500]
    profile = profile_dataframe(frame, "local")

    analysis = inspect_dataframe(frame, profile)
    serialized_profile = profile.to_dict()

    assert analysis["columns_truncated"] is True
    assert analysis["profiled_columns"] == 100
    assert len(analysis["preview"][0]) == 50
    assert len(analysis["preview"][0]["column_0"]) == 200
    assert serialized_profile["column_lists_truncated"] is True


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
    metadata = SourceMetadata("local", "csv", 100, 2, True, 200, "complete", 2)
    monkeypatch.setattr(server_module, "load_dataset", lambda source, threshold: (frame, metadata))

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
    metadata = SourceMetadata("local", "csv", 100, 2, True, 200, "complete", 2)
    monkeypatch.setattr(server_module, "load_dataset", lambda source, threshold: (frame, metadata))

    async def forbidden_show(**kwargs):
        pytest.fail("show must not be called in inspection mode")

    monkeypatch.setattr(server_module, "show", forbidden_show)

    payload = json.loads(await server_module.load_data("sales.csv", visualize=False))

    assert payload["status"] == "success"
    assert payload["visualized"] is False
    assert "url" not in payload
    assert payload["analysis"]["shape"] == {"rows": 2, "columns": 2}
    assert payload["analysis"]["recommendations"]
