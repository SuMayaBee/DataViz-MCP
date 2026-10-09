"""Data loading, profiling, and visualization strategy selection."""

from __future__ import annotations

import io
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
import requests

BIG_DATA_ROWS = 100_000
MAX_REMOTE_BYTES = 100 * 1024 * 1024
SUPPORTED_FORMATS = {".csv", ".json", ".jsonl", ".ndjson", ".parquet"}


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

    def to_dict(self) -> dict:
        """Return a JSON-serializable representation."""
        result = asdict(self)
        result["numeric_columns"] = list(self.numeric_columns)
        result["categorical_columns"] = list(self.categorical_columns)
        return result


def is_remote_source(source: str) -> bool:
    """Return whether *source* is an HTTP(S) URL."""
    return urlparse(source).scheme.lower() in {"http", "https"}


def _source_suffix(source: str) -> str:
    parsed = urlparse(source)
    return Path(parsed.path if parsed.scheme else source).suffix.lower()


def _read_frame(data: bytes | str | Path, suffix: str) -> pd.DataFrame:
    """Read supported tabular data from a path or in-memory byte stream."""
    if suffix == ".csv":
        return pd.read_csv(data)
    if suffix in {".jsonl", ".ndjson"}:
        return pd.read_json(data, lines=True)
    if suffix == ".json":
        return pd.read_json(data)
    if suffix == ".parquet":
        return pd.read_parquet(data)
    raise ValueError(f"Unsupported data format '{suffix or '(none)'}'. Use CSV, JSON, JSONL, NDJSON, or Parquet.")


def load_dataframe(source: str) -> tuple[pd.DataFrame, str]:
    """Load a local or remote tabular dataset and return it with its source kind."""
    suffix = _source_suffix(source)
    if suffix not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported data format '{suffix or '(none)'}'. Use CSV, JSON, JSONL, NDJSON, or Parquet.")

    if is_remote_source(source):
        response = requests.get(source, timeout=30, stream=True)
        response.raise_for_status()
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_REMOTE_BYTES:
                raise ValueError("Remote dataset exceeds the 100 MB download limit.")
            chunks.append(chunk)
        return _read_frame(io.BytesIO(b"".join(chunks)), suffix), "remote"

    path = Path(source).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Data file does not exist: {path}")
    return _read_frame(path, suffix), "local"


def profile_dataframe(frame: pd.DataFrame, source_kind: str, big_data_rows: int = BIG_DATA_ROWS) -> DataProfile:
    """Classify data and select the corresponding visualization strategy."""
    numeric = tuple(str(column) for column in frame.select_dtypes(include="number").columns)
    categorical = tuple(str(column) for column in frame.columns if str(column) not in numeric)

    if source_kind == "remote":
        category = "remote_data"
        strategy = "hvplot"
    elif len(frame) >= big_data_rows:
        category = "big_data"
        strategy = "datashader"
    elif len(numeric) >= 3:
        category = "multidimensional_data"
        strategy = "holoviews"
    else:
        category = "simple_data"
        strategy = "hvplot"

    return DataProfile(
        category=category,
        source_kind=source_kind,
        rows=len(frame),
        columns=len(frame.columns),
        numeric_columns=numeric,
        categorical_columns=categorical,
        strategy=strategy,
    )


def _loader_code(source: str) -> list[str]:
    """Build safe, literal Python statements that reload *source* for rendering."""
    suffix = _source_suffix(source)
    reader = {
        ".csv": "pd.read_csv",
        ".json": "pd.read_json",
        ".jsonl": "lambda value: pd.read_json(value, lines=True)",
        ".ndjson": "lambda value: pd.read_json(value, lines=True)",
        ".parquet": "pd.read_parquet",
    }[suffix]
    if is_remote_source(source):
        return [
            "import io",
            "import requests",
            f"response = requests.get({source!r}, timeout=30)",
            "response.raise_for_status()",
            f"df = ({reader})(io.BytesIO(response.content))",
        ]
    path = str(Path(source).expanduser().resolve())
    return [f"df = ({reader})({path!r})"]


def _axes(frame: pd.DataFrame, profile: DataProfile) -> tuple[str, str, str | None]:
    """Select useful x, y, and optional color dimensions."""
    if len(profile.numeric_columns) >= 2:
        color = profile.numeric_columns[2] if len(profile.numeric_columns) >= 3 else None
        return profile.numeric_columns[0], profile.numeric_columns[1], color
    if profile.numeric_columns and profile.categorical_columns:
        return profile.categorical_columns[0], profile.numeric_columns[0], None
    if profile.numeric_columns:
        return "__index__", profile.numeric_columns[0], None
    if profile.categorical_columns:
        return profile.categorical_columns[0], "__count__", None
    raise ValueError("The dataset has no columns to visualize.")


def build_visualization_code(source: str, frame: pd.DataFrame, profile: DataProfile, title: str) -> str:
    """Generate plotting code for the strategy selected in *profile*."""
    x, y, color = _axes(frame, profile)
    lines = ["import pandas as pd", *_loader_code(source)]

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
