---
name: dataviz-plot-selection
description: Select and generate clear plots with DataViz MCP from a dataset or analytical question. Use when choosing chart type, visual encodings, aggregation, HoloViz renderer, or the load_data versus show workflow for simple, remote, multidimensional, or large data.
---

# DataViz Plot Selection

Choose the plot from the user's question and the data's structure. Do not select a chart only
because a library supports it. Preserve any chart type, columns, aggregation, or style the user
explicitly requests unless it would be misleading or cannot render.

## Workflow

1. Identify the analytical intent: trend, comparison, distribution, relationship, composition,
   geography, hierarchy, flow, or multidimensional exploration.
2. Inspect the relevant columns, types, missing values, cardinality, row count, units, and time
   grain. Use `load_data` when the user provides a local supported file or remote data URL and
   wants automatic selection. Use `show` for a custom chart or dashboard.
3. Select the chart and encodings from [references/use-cases.md](references/use-cases.md).
4. Prefer hvPlot for ordinary DataFrame plots, HoloViews for composable or multidimensional
   views, Datashader for dense large data, and Panel for widgets or multi-view dashboards.
5. Label axes and units, use a descriptive title, keep legends readable, and state material
   filtering or aggregation in the description.
6. Render, then use `screenshot` to check clipping, empty output, unreadable labels, misleading
   scales, and excessive overlap before presenting the visualization.

## Data-scale routing

- Remote data: use `load_data`; it validates the format and uses the normal hvPlot path.
- Local data with at least 100,000 rows: use the Datashader strategy. Prefer `rasterize=True`
  for numeric point density so axes, hover, and color mapping remain interactive.
- Local data with at least three numeric dimensions: use HoloViews and encode the additional
  dimensions through color, size, facets, or linked views. Do not force every dimension into one
  overloaded plot.
- Smaller local data: use hvPlot unless the requested interaction needs HoloViews or Panel.

## Integrity rules

- Bar charts start at zero unless a clearly disclosed analytical reason requires otherwise.
- Aggregate duplicate categories or time periods deliberately; never rely on overplotting to
  imply aggregation.
- Use chronological ordering for time and meaningful ordering for categories.
- Avoid pie charts when values are close or there are more than five categories.
- Avoid dual axes when normalized or faceted views can make the comparison honestly.
- For dense scatter plots, use transparency for moderate overlap and Datashader for heavy overlap.
- Treat missing values explicitly. Do not silently convert them to zero.
- Do not imply causation from correlation or use a smoothed trend without making it visible.

## DataViz MCP rendering contract

- Pass generated code directly to `show`; do not create a script or notebook.
- Use `method="inline"` and end with the plot object for a single plot.
- Use `method="server"` and call `.servable()` for widgets, reactive controls, or a Panel layout.
- Give every result a short `name` and a useful one-sentence `description`.
- Return the live URL as `[Show Visualization](url)`.
