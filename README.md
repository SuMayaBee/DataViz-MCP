# ✨ dataviz-mcp

[![CI](https://img.shields.io/github/actions/workflow/status/SuMayaBee/DataViz-MCP/ci.yml?style=flat-square&branch=main)](https://github.com/SuMayaBee/DataViz-MCP/actions/workflows/ci.yml)
[![conda-forge](https://img.shields.io/conda/vn/conda-forge/dataviz-mcp?logoColor=white&logo=conda-forge&style=flat-square)](https://prefix.dev/channels/conda-forge/packages/dataviz-mcp)
[![pypi-version](https://img.shields.io/pypi/v/dataviz-mcp.svg?logo=pypi&logoColor=white&style=flat-square)](https://pypi.org/project/dataviz-mcp)
[![python-version](https://img.shields.io/pypi/pyversions/dataviz-mcp?logoColor=white&logo=python&style=flat-square)](https://pypi.org/project/dataviz-mcp)

DataViz MCP is a local Panel web server and MCP server that executes Python code snippets
and renders the resulting visualizations as live, interactive web pages — enabling humans and AI
assistants to display and inspect Python outputs in real time.

![dataviz-mcp showcase](https://raw.githubusercontent.com/SuMayaBee/DataViz-MCP/main/docs/assets/gif/dataviz-mcp-showcase.gif)

![dataviz-mcp MCP showcase](https://raw.githubusercontent.com/SuMayaBee/DataViz-MCP/main/docs/assets/gif/dataviz-mcp-showcase-mcp.gif)

## Features

- **Two interfaces** — `pls serve` (standalone browser UI) and `pls mcp` (MCP server for AI assistants)
- **Any visualization library** — hvplot · plotly · altair · matplotlib · seaborn · holoviews · bokeh · and more
- **Validate before render** — `show` runs syntax, security, package, and extension checks before any rendering happens
- **Visual validation** — `screenshot` MCP tool lets the AI inspect the rendered output visually before presenting it
- **Adaptive data loading** — `load_data` detects remote, large, multidimensional, and simple tabular data, then selects hvPlot, HoloViews, or Datashader automatically
- **Persistent storage** — SQLite database with full-text search; every snippet gets its own permanent URL
- **Auto-restart** — Panel subprocess is health-monitored and automatically restarted on failure
- **Works everywhere** — local, JupyterHub, GitHub Codespaces; URLs externalized automatically

## Installation

Install via uv, pip, or pixi — see the [Installation guide](https://SuMayaBee.github.io/DataViz-MCP/tutorials/installation/) for full instructions including how to find your `pls` path.

```bash
uv tool install "dataviz-mcp[pydata]"
```

> **Pin your version** — this project is in its early stages. Pin to a specific version to avoid
> unexpected changes: `uv tool install "dataviz-mcp[pydata]==0.1.0a1"`

## Connect to your AI assistant

Use the **absolute path** printed by `which pls` above — not just `pls`.
Full setup instructions for each client: [docs → Connect to your MCP client](https://SuMayaBee.github.io/DataViz-MCP/tutorials/installation/#connect-to-your-mcp-client)

For the supported desktop and editor clients, let DataViz MCP add just its own
configuration entry while preserving any other configured servers:

```bash
pls install cursor
# also: vscode, claude-desktop, windsurf, cline, gemini, kiro, copilot
```

You can tailor the AI guidance without forking the project. Put optional
`"instructions"` and `"screenshot"` additions in a JSON file, then start the
MCP server with `pls mcp --prompts rules.json`.

| Client | Config location |
|---|---|
| **VS Code** | `.vscode/mcp.json` |
| **Cursor** | `~/.cursor/mcp.json` |
| **Claude Desktop** | `claude_desktop_config.json` |
| **Claude Code** | `claude mcp add dataviz-mcp -- /path/to/pls mcp` |
| **claude.ai** | HTTP transport + tunnel — see [docs](https://SuMayaBee.github.io/DataViz-MCP/tutorials/installation/#connect-to-your-mcp-client) |

## Usage

For a safe visual iteration loop, use `screenshot(code=...)` to review a private
draft, use `edit(...)` for small source changes, then call `show(draft_id=...)`
to publish exactly the reviewed result. Use `evaluate(code=...)` for text-only
Python checks that do not need a rendered visualization.

To load and visualize tabular data automatically, ask the assistant to call
`load_data(source=...)` with a local CSV, JSON, JSONL, NDJSON, or Parquet path,
or an HTTP(S) URL. The tool profiles the data and selects hvPlot for simple or
remote data, HoloViews for multidimensional data, and Datashader for large data.
Set `visualize=False` when the request is only to inspect or understand the data;
the same tool returns schema, quality statistics, a preview, and recommended chart
types without creating a visualization or feed entry.

The packaged [`dataviz-plot-selection`](skills/dataviz-plot-selection/SKILL.md)
skill guides chart choice for trends, comparisons, distributions, relationships,
composition, maps, multidimensional exploration, and dashboards. Its guidance is
loaded into the MCP server instructions automatically whenever plots are created.

```
$ pls

 Usage: pls [OPTIONS] COMMAND [ARGS]...

 DataViz MCP - Execute and visualize Python code snippets.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────╮
│ --version  -V        Show version and exit.                                                          │
│ --help               Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────╮
│ serve   Start the DataViz MCP directly.                                                        │
│ mcp     Start as an MCP server for AI assistants.                                                    │
│ status  Check whether the Panel server is running.                                                   │
│ list    List resources (packages, etc.).                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

You can also use `dataviz-mcp` but `pls` is shorter and easier to remember.

## Development

See the [Contributing guide](https://SuMayaBee.github.io/DataViz-MCP/tutorials/contributing/) for the full setup (fork, install, connect to MCP client, run tests).

## ❤️ Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch: `git checkout -b feature/YourFeature`.
3. Make your changes and commit them: `git commit -m 'Add some feature'`.
4. Push to the branch: `git push origin feature/YourFeature`.
5. Open a pull request.

Please ensure your code passes all tests and linting before submitting.
