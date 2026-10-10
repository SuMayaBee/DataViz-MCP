"""Data loading, profiling, and visualization strategy selection."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlparse

import pandas as pd
import requests
import xarray as xr

BIG_DATA_ROWS = 100_000
BIG_FILE_BYTES = 100 * 1024 * 1024
BIG_MEMORY_BYTES = 500 * 1024 * 1024
BIG_DATA_COLUMNS = 500
PROFILE_SAMPLE_ROWS = 10_000
MAX_PROFILE_COLUMNS = 100
MAX_PREVIEW_COLUMNS = 50
MAX_NUMERIC_SUMMARY_COLUMNS = 20
MAX_TEXT_LENGTH = 200
MAX_REMOTE_BYTES = 100 * 1024 * 1024
SUPPORTED_FORMATS = {".csv", ".json", ".jsonl", ".ndjson", ".parquet", ".nc"}

_IDENTIFIER_NAMES = {"id", "uuid", "index", "row", "row_number"}
_TIME_COMPONENT_NAMES = {"year", "month", "day", "hour", "minute", "second"}
_MEASURE_TOKENS = (
    "delay",
    "distance",
    "duration",
    "amount",
    "price",
    "cost",
    "sales",
    "revenue",
    "profit",
    "value",
    "score",
    "temperature",
    "speed",
    "weight",
    "height",
    "length",
)


@dataclass(frozen=True)
class SourceMetadata:
    """Preflight facts gathered without retaining the complete dataset in memory."""

    source_kind: str
    format: str
    size_bytes: int
    estimated_rows: int
    row_count_exact: bool
    estimated_memory_bytes: int
    profile_mode: str
    loaded_rows: int
    dimensions: tuple[str, ...] = ()
    data_variables: tuple[str, ...] = ()
    selected_variable: str = ""


@dataclass(frozen=True)
class DataProfile:
    """A compact description of a loaded tabular dataset."""

    category: str
    source_kind: str
    rows: int
    columns: int
    numeric_columns: tuple[str, ...]
    categorical_columns: tuple[str, ...]
    strategy: str
    format: str = "unknown"
    size_bytes: int = 0
    estimated_memory_bytes: int = 0
    profile_mode: str = "complete"
    loaded_rows: int = 0
    row_count_exact: bool = True
    traits: tuple[str, ...] = ()
    dimensions: tuple[str, ...] = ()
    data_variables: tuple[str, ...] = ()
    selected_variable: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""
        result = asdict(self)
        result["numeric_columns"] = list(self.numeric_columns[:MAX_PROFILE_COLUMNS])
        result["categorical_columns"] = list(self.categorical_columns[:MAX_PROFILE_COLUMNS])
        result["column_lists_truncated"] = len(self.numeric_columns) > MAX_PROFILE_COLUMNS or len(self.categorical_columns) > MAX_PROFILE_COLUMNS
        result["traits"] = list(self.traits)
        result["dimensions"] = list(self.dimensions)
        result["data_variables"] = list(self.data_variables[:MAX_PROFILE_COLUMNS])
        return result


def recommend_visualizations(frame: pd.DataFrame, profile: DataProfile) -> list[dict[str, str]]:
    """Recommend useful visualization types from the dataset structure."""
    recommendations: list[dict[str, str]] = []
    numeric = _plot_numeric_columns(frame, profile)
    categorical = list(profile.categorical_columns)
    time_columns = [
        str(column)
        for column in frame.columns
        if pd.api.types.is_datetime64_any_dtype(frame[column]) or any(token in str(column).lower() for token in ("date", "time", "year", "month"))
    ]

    if profile.category == "big_data" and len(numeric) >= 2:
        recommendations.append(
            {
                "type": "Datashader scatter plot",
                "columns": f"{numeric[0]} vs {numeric[1]}",
                "reason": "Rasterization keeps a dense dataset responsive and reveals point concentration.",
                "library": "Datashader through hvPlot",
            }
        )
    if time_columns and numeric:
        recommendations.append(
            {
                "type": "Line chart",
                "columns": f"{time_columns[0]} and {numeric[0]}",
                "reason": "Shows how the numeric measure changes over time.",
                "library": "hvPlot",
            }
        )
    if categorical and numeric:
        recommendations.append(
            {
                "type": "Bar chart",
                "columns": f"{categorical[0]} and {numeric[0]}",
                "reason": "Compares an aggregated numeric measure across categories.",
                "library": "hvPlot",
            }
        )
    if len(numeric) >= 2:
        recommendations.append(
            {
                "type": "Scatter plot",
                "columns": f"{numeric[0]} vs {numeric[1]}",
                "reason": "Reveals association, clusters, and outliers between two numeric variables.",
                "library": "HoloViews" if len(numeric) >= 3 else "hvPlot",
            }
        )
    if len(numeric) >= 3:
        recommendations.append(
            {
                "type": "Multidimensional scatter plot",
                "columns": f"{numeric[0]}, {numeric[1]}, and {numeric[2]}",
                "reason": "Uses position and color to explore three numeric dimensions together.",
                "library": "HoloViews",
            }
        )
    if numeric:
        recommendations.append(
            {
                "type": "Histogram",
                "columns": numeric[0],
                "reason": "Shows the distribution, spread, and possible skew of a numeric variable.",
                "library": "hvPlot",
            }
        )
    if categorical:
        recommendations.append(
            {
                "type": "Count bar chart",
                "columns": categorical[0],
                "reason": "Shows the frequency of each category.",
                "library": "hvPlot",
            }
        )
    return recommendations


def _is_identifier_column(frame: pd.DataFrame, column: str) -> bool:
    """Return whether a numeric column behaves like an exported row identifier."""
    normalized = column.strip().lower()
    if not normalized or normalized.startswith("unnamed:"):
        return True
    if normalized in _IDENTIFIER_NAMES or normalized.endswith("_id"):
        return True
    return False


def _plot_numeric_columns(frame: pd.DataFrame, profile: DataProfile) -> list[str]:
    """Rank useful numeric measures while excluding constants and identifiers."""
    candidates: list[tuple[int, int, str]] = []
    for position, column in enumerate(profile.numeric_columns):
        if column not in frame.columns:
            continue
        values = frame[column].dropna()
        if values.nunique() <= 1 or _is_identifier_column(frame, column):
            continue
        normalized = column.strip().lower()
        score = 0
        if any(token in normalized for token in _MEASURE_TOKENS):
            score += 100
        if "delay" in normalized:
            score += 100
        if normalized in _TIME_COMPONENT_NAMES:
            score -= 100
        if normalized in {"flight", "zip", "zipcode", "code"}:
            score -= 75
        candidates.append((score, -position, column))
    candidates.sort(reverse=True)
    ranked = [column for _, _, column in candidates]
    if ranked:
        return ranked
    # A one-row preview makes every measure appear constant. Preserve a useful
    # fallback for tiny datasets while still rejecting obvious index columns.
    return [column for column in profile.numeric_columns if column in frame.columns and not _is_identifier_column(frame, column)]


def inspect_dataframe(frame: pd.DataFrame, profile: DataProfile) -> dict:
    """Build a JSON-safe structural and statistical summary of *frame*."""
    profiled_columns = list(frame.columns[:MAX_PROFILE_COLUMNS])
    columns = [
        {
            "name": str(column),
            "dtype": str(frame[column].dtype),
            "missing": int(frame[column].isna().sum()),
            "unique": int(frame[column].nunique(dropna=True)),
        }
        for column in profiled_columns
    ]
    numeric_summary: dict = {}
    if profile.numeric_columns:
        summary_columns = list(profile.numeric_columns[:MAX_NUMERIC_SUMMARY_COLUMNS])
        summary = frame[summary_columns].describe().round(4)
        numeric_summary = json.loads(summary.to_json())
    preview_frame = frame.iloc[:5, :MAX_PREVIEW_COLUMNS].copy()
    for column in preview_frame.select_dtypes(include=["object", "string"]).columns:
        preview_frame[column] = preview_frame[column].map(lambda value: value[:MAX_TEXT_LENGTH] if isinstance(value, str) else value)
    preview = json.loads(preview_frame.to_json(orient="records", date_format="iso"))
    return {
        "shape": {"rows": profile.rows, "columns": profile.columns},
        "profile_mode": profile.profile_mode,
        "profiled_rows": len(frame),
        "profiled_columns": len(profiled_columns),
        "columns_truncated": len(frame.columns) > MAX_PROFILE_COLUMNS,
        "statistics_scope": "sample" if profile.profile_mode == "sampled" else "complete dataset",
        "columns": columns,
        "missing_values": int(frame.isna().sum().sum()),
        "duplicate_rows": int(frame.duplicated().sum()),
        "numeric_summary": numeric_summary,
        "preview": preview,
        "recommendations": recommend_visualizations(frame, profile),
    }


def is_remote_source(source: str) -> bool:
    """Return whether *source* is an HTTP(S) URL."""
    return urlparse(source).scheme.lower() in {"http", "https"}


def _source_suffix(source: str) -> str:
    parsed = urlparse(source)
    return Path(parsed.path if parsed.scheme else source).suffix.lower()


def _read_frame(data: bytes | str | Path | BinaryIO, suffix: str, row_limit: int | None = None) -> pd.DataFrame:
    """Read supported tabular data from a path or in-memory byte stream."""
    if suffix == ".csv":
        return pd.read_csv(data, nrows=row_limit)
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(data, lines=True, nrows=row_limit)
    if suffix == ".json":
        frame = pd.read_json(data)
        return frame.head(row_limit) if row_limit else frame
    if suffix == ".parquet":
        if row_limit:
            try:
                import pyarrow.parquet as pq

                parquet = pq.ParquetFile(data)
                batches = parquet.iter_batches(batch_size=row_limit)
                return next(batches).to_pandas().head(row_limit)
            except (ImportError, StopIteration):
                pass
        frame = pd.read_parquet(data)
        return frame.head(row_limit) if row_limit else frame
    raise ValueError(f"Unsupported data format '{suffix or '(none)'}'. Use CSV, JSON, JSONL, NDJSON, Parquet, or NetCDF.")


def _select_netcdf_variable(dataset: xr.Dataset) -> str:
    """Choose the largest numeric variable with at least one dimension."""
    candidates = [
        str(name)
        for name, array in dataset.data_vars.items()
        if array.ndim > 0 and pd.api.types.is_numeric_dtype(array.dtype)
    ]
    if not candidates:
        raise ValueError("The NetCDF dataset has no numeric data variable to visualize.")
    return max(candidates, key=lambda name: dataset[name].size)


def _netcdf_frame(array: xr.DataArray, row_limit: int | None) -> pd.DataFrame:
    """Convert an Xarray variable to a bounded tidy DataFrame."""
    bounded = array
    if row_limit and array.size > row_limit:
        remaining = max(1, int(array.size / max(1, array.sizes[array.dims[0]])))
        first_dimension_rows = max(1, min(array.sizes[array.dims[0]], (row_limit + remaining - 1) // remaining))
        bounded = array.isel({array.dims[0]: slice(0, first_dimension_rows)})
    value_name = str(array.name or "value")
    return bounded.to_dataframe(name=value_name).reset_index().head(row_limit)


def _load_netcdf_inspected(
    data: str | Path | BinaryIO,
    source_kind: str,
    size_bytes: int,
    big_data_rows: int,
) -> tuple[pd.DataFrame, SourceMetadata]:
    """Read NetCDF metadata first and materialize only the selected variable."""
    if hasattr(data, "seek"):
        data.seek(0)
    with xr.open_dataset(data) as dataset:
        variable = _select_netcdf_variable(dataset)
        array = dataset[variable]
        rows = int(array.size)
        dimensions = tuple(str(dimension) for dimension in array.dims)
        variables = tuple(str(name) for name in dataset.data_vars)
        sample = _netcdf_frame(array, PROFILE_SAMPLE_ROWS)
        memory_bytes = int(array.nbytes)
        columns = len(sample.columns)
        big = _is_big(rows, columns, size_bytes, memory_bytes, big_data_rows)
        frame = sample if big else _netcdf_frame(array, None)

    return frame, SourceMetadata(
        source_kind=source_kind,
        format="netcdf",
        size_bytes=size_bytes,
        estimated_rows=rows,
        row_count_exact=True,
        estimated_memory_bytes=memory_bytes,
        profile_mode="sampled" if big else "complete",
        loaded_rows=len(frame),
        dimensions=dimensions,
        data_variables=variables,
        selected_variable=variable,
    )


def _count_rows(data: str | Path | BinaryIO, suffix: str) -> tuple[int, bool]:
    """Count records by streaming, or obtain the count from format metadata."""
    if hasattr(data, "seek"):
        data.seek(0)
    if suffix == ".csv":
        rows = sum(len(chunk) for chunk in pd.read_csv(data, chunksize=50_000))
        exact = True
    elif suffix in {".jsonl", ".ndjson"}:
        if hasattr(data, "read"):
            rows = sum(1 for line in data if line.strip())
        else:
            with Path(data).open("rb") as stream:
                rows = sum(1 for line in stream if line.strip())
        exact = True
    elif suffix == ".parquet":
        try:
            import pyarrow.parquet as pq

            rows = pq.ParquetFile(data).metadata.num_rows
            exact = True
        except ImportError:
            rows = 0
            exact = False
    else:
        rows = 0
        exact = False
    if hasattr(data, "seek"):
        data.seek(0)
    return rows, exact


def _estimated_memory(sample: pd.DataFrame, rows: int) -> int:
    """Estimate total in-memory size from a bounded sample."""
    if sample.empty or rows <= 0:
        return 0
    sample_bytes = int(sample.memory_usage(index=True, deep=True).sum())
    return int((sample_bytes / len(sample)) * rows)


def _estimate_rows_from_size(sample: pd.DataFrame, size_bytes: int) -> int:
    """Estimate rows for non-streamable formats from file size and sample width."""
    if sample.empty:
        return 0
    bytes_per_row = max(1, int(sample.memory_usage(index=False, deep=True).sum() / len(sample)))
    return max(len(sample), size_bytes // bytes_per_row)


def _is_big(rows: int, columns: int, size_bytes: int, memory_bytes: int, threshold: int) -> bool:
    return rows >= threshold or columns >= BIG_DATA_COLUMNS or size_bytes >= BIG_FILE_BYTES or memory_bytes >= BIG_MEMORY_BYTES


def _download_remote(source: str) -> tuple[tempfile.SpooledTemporaryFile, int]:
    """Stream a remote dataset into a disk-backed temporary file with a hard limit."""
    response = requests.get(source, timeout=30, stream=True)
    response.raise_for_status()
    stream = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    total = 0
    for chunk in response.iter_content(chunk_size=1024 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > MAX_REMOTE_BYTES:
            stream.close()
            raise ValueError("Remote dataset exceeds the 100 MB download limit.")
        stream.write(chunk)
    stream.seek(0)
    return stream, total


def _load_inspected(data: str | Path | BinaryIO, suffix: str, source_kind: str, size_bytes: int, big_data_rows: int) -> tuple[pd.DataFrame, SourceMetadata]:
    """Inspect a source first, then fully load it or retain only a bounded sample."""
    if suffix == ".nc":
        return _load_netcdf_inspected(data, source_kind, size_bytes, big_data_rows)
    rows, exact = _count_rows(data, suffix)
    if hasattr(data, "seek"):
        data.seek(0)
    sample = _read_frame(data, suffix, PROFILE_SAMPLE_ROWS)
    if not exact:
        rows = _estimate_rows_from_size(sample, size_bytes)
    memory_bytes = _estimated_memory(sample, rows)
    big = _is_big(rows, len(sample.columns), size_bytes, memory_bytes, big_data_rows)

    if big:
        frame = sample
        profile_mode = "sampled"
    else:
        if hasattr(data, "seek"):
            data.seek(0)
        frame = _read_frame(data, suffix)
        rows = len(frame)
        exact = True
        memory_bytes = int(frame.memory_usage(index=True, deep=True).sum())
        profile_mode = "complete"

    return frame, SourceMetadata(
        source_kind=source_kind,
        format=suffix.removeprefix("."),
        size_bytes=size_bytes,
        estimated_rows=rows,
        row_count_exact=exact,
        estimated_memory_bytes=memory_bytes,
        profile_mode=profile_mode,
        loaded_rows=len(frame),
    )


def load_dataset(source: str, big_data_rows: int = BIG_DATA_ROWS) -> tuple[pd.DataFrame, SourceMetadata]:
    """Preflight and load a dataset, sampling sources classified as large."""
    suffix = _source_suffix(source)
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported data format '{suffix or '(none)'}'. Use CSV, JSON, JSONL, NDJSON, Parquet, or NetCDF.")

    if is_remote_source(source):
        stream, size_bytes = _download_remote(source)
        try:
            return _load_inspected(stream, suffix, "remote", size_bytes, big_data_rows)
        finally:
            stream.close()

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Data file does not exist: {path}")
    return _load_inspected(path, suffix, "local", path.stat().st_size, big_data_rows)


def load_dataframe(source: str) -> tuple[pd.DataFrame, str]:
    """Compatibility wrapper returning the frame and source kind."""
    frame, metadata = load_dataset(source)
    return frame, metadata.source_kind


def profile_dataframe(
    frame: pd.DataFrame,
    source_kind: str,
    big_data_rows: int = BIG_DATA_ROWS,
    metadata: SourceMetadata | None = None,
) -> DataProfile:
    """Classify data and select the corresponding visualization strategy."""
    numeric = tuple(str(column) for column in frame.select_dtypes(include="number").columns)
    categorical = tuple(str(column) for column in frame.columns if str(column) not in numeric)

    rows = metadata.estimated_rows if metadata else len(frame)
    size_bytes = metadata.size_bytes if metadata else 0
    memory_bytes = metadata.estimated_memory_bytes if metadata else int(frame.memory_usage(index=True, deep=True).sum())
    useful_columns = [
        column
        for column in frame.columns
        if frame[column].nunique(dropna=True) > 1
        and frame[column].isna().mean() < 0.8
        and not (str(column).lower() in {"id", "uuid"} or str(column).lower().endswith("_id"))
    ]
    multidimensional = bool(metadata and len(metadata.dimensions) >= 2) or len(numeric) >= 3 or len(useful_columns) >= 5
    big = _is_big(rows, len(frame.columns), size_bytes, memory_bytes, big_data_rows)

    if big:
        category = "big_data"
        strategy = "datashader"
    elif multidimensional:
        category = "multidimensional_data"
        strategy = "holoviews" if len(numeric) >= 3 else "hvplot"
    else:
        category = "simple_data"
        strategy = "hvplot"

    traits: list[str] = []
    if multidimensional:
        traits.append("multidimensional")
    if metadata and metadata.format == "netcdf":
        traits.append("labeled_array")
    if numeric and categorical:
        traits.append("mixed_types")
    if any(pd.api.types.is_datetime64_any_dtype(frame[column]) or any(token in str(column).lower() for token in ("date", "time")) for column in frame.columns):
        traits.append("time_series")

    return DataProfile(
        category=category,
        source_kind=source_kind,
        rows=rows,
        columns=len(frame.columns),
        numeric_columns=numeric,
        categorical_columns=categorical,
        strategy=strategy,
        format=metadata.format if metadata else "unknown",
        size_bytes=size_bytes,
        estimated_memory_bytes=memory_bytes,
        profile_mode=metadata.profile_mode if metadata else "complete",
        loaded_rows=metadata.loaded_rows if metadata else len(frame),
        row_count_exact=metadata.row_count_exact if metadata else True,
        traits=tuple(traits),
        dimensions=metadata.dimensions if metadata else (),
        data_variables=metadata.data_variables if metadata else (),
        selected_variable=metadata.selected_variable if metadata else "",
    )


def _loader_code(source: str, profile: DataProfile) -> list[str]:
    """Build safe, literal Python statements that reload *source* for rendering."""
    suffix = _source_suffix(source)
    sampled = profile.profile_mode == "sampled"
    limit = PROFILE_SAMPLE_ROWS

    if suffix == ".nc":
        variable = profile.selected_variable
        if is_remote_source(source):
            lines = [
                "import io",
                "import requests",
                "import xarray as xr",
                f"response = requests.get({source!r}, timeout=30)",
                "response.raise_for_status()",
                "ds = xr.open_dataset(io.BytesIO(response.content))",
            ]
        else:
            path = str(Path(source).expanduser().resolve())
            lines = ["import xarray as xr", f"ds = xr.open_dataset({path!r})"]
        lines.append(f"da = ds[{variable!r}]")
        lines.append("if 'time' in da.dims and da.ndim >= 3: da = da.isel(time=0)")
        if sampled:
            lines.extend(
                [
                    "remaining = max(1, int(da.size / max(1, da.sizes[da.dims[0]])))",
                    f"take = max(1, min(da.sizes[da.dims[0]], ({limit} + remaining - 1) // remaining))",
                    "da = da.isel({da.dims[0]: slice(0, take)})",
                ]
            )
        lines.append(f"df = da.to_dataframe(name={variable!r}).reset_index().head({limit})")
        return lines

    def read_expression(value: str) -> str:
        if suffix == ".csv":
            return f"pd.read_csv({value}, nrows={limit})" if sampled else f"pd.read_csv({value})"
        if suffix in {".jsonl", ".ndjson"}:
            return f"pd.read_json({value}, lines=True, nrows={limit})" if sampled else f"pd.read_json({value}, lines=True)"
        if suffix == ".json":
            expression = f"pd.read_json({value})"
            return f"({expression}).head({limit})" if sampled else expression
        expression = f"pd.read_parquet({value})"
        return f"({expression}).head({limit})" if sampled else expression

    if is_remote_source(source):
        return [
            "import io",
            "import requests",
            f"response = requests.get({source!r}, timeout=30)",
            "response.raise_for_status()",
            f"df = {read_expression('io.BytesIO(response.content)')}",
        ]
    path = str(Path(source).expanduser().resolve())
    return [f"df = {read_expression(repr(path))}"]


def _axes(frame: pd.DataFrame, profile: DataProfile) -> tuple[str, str, str | None]:
    """Select useful x, y, and optional color dimensions."""
    if profile.selected_variable in profile.numeric_columns:
        numeric_dimensions = [dimension for dimension in profile.dimensions if dimension in profile.numeric_columns]
        if len(numeric_dimensions) >= 2:
            return numeric_dimensions[-1], numeric_dimensions[-2], profile.selected_variable
    numeric = _plot_numeric_columns(frame, profile)
    if len(numeric) >= 2:
        color = numeric[2] if len(numeric) >= 3 else None
        return numeric[0], numeric[1], color
    if numeric and profile.categorical_columns:
        return profile.categorical_columns[0], numeric[0], None
    if numeric:
        return "__index__", numeric[0], None
    if profile.categorical_columns:
        return profile.categorical_columns[0], "__count__", None
    raise ValueError("The dataset has no columns to visualize.")


def build_visualization_code(source: str, frame: pd.DataFrame, profile: DataProfile, title: str) -> str:
    """Generate plotting code for the strategy selected in *profile*."""
    x, y, color = _axes(frame, profile)
    lines = ["import pandas as pd", *_loader_code(source, profile)]

    if x == "__index__":
        lines.extend(["df = df.reset_index()", "x = df.columns[0]", f"y = {y!r}"])
    elif y == "__count__":
        lines.extend([f"df = df[{x!r}].value_counts().rename_axis({x!r}).reset_index(name='count')", f"x = {x!r}", "y = 'count'"])
    else:
        lines.extend([f"x = {x!r}", f"y = {y!r}"])

    if profile.strategy == "datashader":
        lines.extend(
            [
                "import hvplot.pandas",
                "import datashader",
                f"plot = df.hvplot.scatter(x=x, y=y, rasterize=True, dynspread=True, width=900, height=520, title={title!r})",
            ]
        )
    elif profile.strategy == "holoviews":
        lines.extend(
            [
                "import holoviews as hv",
                "hv.extension('bokeh')",
                f"color = {color!r}",
                "plot = hv.Scatter(df, kdims=[x], vdims=[y, color]).opts("
                f"color=color, colorbar=True, cmap='Viridis', tools=['hover'], width=900, height=520, title={title!r})",
            ]
        )
    else:
        lines.append("import hvplot.pandas")
        if x in profile.categorical_columns:
            lines.append(f"plot = df.hvplot.bar(x=x, y=y, width=900, height=520, title={title!r})")
        elif len(profile.numeric_columns) >= 2:
            lines.append(f"plot = df.hvplot.scatter(x=x, y=y, width=900, height=520, title={title!r})")
        else:
            lines.append(f"plot = df.hvplot.line(x=x, y=y, width=900, height=520, title={title!r})")

    lines.append("plot")
    return "\n".join(lines)
