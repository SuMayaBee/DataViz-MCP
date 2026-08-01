# Contributing

Contributions are welcome! This guide walks you through forking the repository, setting up a
local development environment, and connecting your local build to an MCP client.

---

## Step 1: Fork and clone

1. [Fork the repository](https://github.com/SuMayaBee/DataViz-MCP/fork) on GitHub.
2. Clone your fork:

```bash
git clone https://github.com/<your-username>/DataViz-MCP.git
cd DataViz-MCP
```

3. Create a feature branch:

```bash
git checkout -b feature/YourFeature
```

---

## Step 2: Install

=== "pixi"

    Install the environment:

    ```bash
    pixi install
    ```

    Run the post-install step (editable install plus Chromium setup):

    ```bash
    pixi run postinstall
    ```

    Find the `pls` path:

    **macOS / Linux:**

    ```bash
    pixi run which pls
    # typically: /path/to/dataviz-mcp/.pixi/envs/default/bin/pls
    ```

    **Windows:**

    ```powershell
    pixi run where.exe pls
    # typically: .pixi\envs\default\Library\bin\pls.exe
    ```

    !!! note
        Prefix commands with `pixi run` (e.g. `pixi run pytest`) to use the pixi env without
        activating it. `pixi run postinstall` already installs Chromium automatically.

=== "uv"

    Create and activate a virtual environment.

    **macOS / Linux:**

    ```bash
    uv venv
    source .venv/bin/activate
    ```

    **Windows (PowerShell):**

    ```powershell
    uv venv
    .venv\Scripts\Activate.ps1
    ```

    **Windows (Command Prompt):**

    ```bat
    uv venv
    .venv\Scripts\activate.bat
    ```

    Install the package in editable mode:

    ```bash
    uv pip install -e ".[dev]"
    ```

    Install the browser binary needed by the `screenshot` MCP tool:

    ```bash
    playwright install chromium
    ```

    Find the `pls` path:

    **macOS / Linux:**

    ```bash
    which pls
    # typically: /path/to/dataviz-mcp/.venv/bin/pls
    ```

    **Windows:**

    ```powershell
    where.exe pls
    # typically: .venv\Scripts\pls.exe
    ```

    !!! note
        Re-activate the venv in every new terminal (see above).
        `playwright install chromium` is a one-time step that downloads the browser binary
        (~150 MB) required by the `screenshot` MCP tool.

---

## Step 3: Install pre-commit hooks

=== "pixi"

    ```bash
    pixi run lint-install
    ```

=== "uv"

    ```bash
    pre-commit install
    ```

---

## Step 4: Connect to your MCP client

Use the absolute path from `pixi run which pls` (pixi) or `which pls` (uv) above, or
`where.exe pls` on Windows.

=== "VS Code"

    Add to `.vscode/mcp.json` (create if it doesn't exist):

    ```json
    {
      "servers": {
        "dataviz-mcp": {
          "type": "stdio",
          "command": "/path/to/pls",
          "args": ["mcp"]
        }
      }
    }
    ```

    !!! warning "Use your absolute path"
        Replace `"command": "/path/to/pls"` with the path printed above,
        e.g. `"command": "/path/to/dataviz-mcp/.venv/bin/pls"`

=== "Cursor"

    Add to `~/.cursor/mcp.json`:

    ```json
    {
      "mcpServers": {
        "dataviz-mcp": {
          "command": "/path/to/pls",
          "args": ["mcp"]
        }
      }
    }
    ```

    !!! warning "Use your absolute path"
        Replace `"command": "/path/to/pls"` with the path printed above,
        e.g. `"command": "/path/to/dataviz-mcp/.venv/bin/pls"`

    Open Cursor Settings → MCP and verify the green dot. Use Agent mode in chat.

=== "Claude Desktop"

    Edit the config file for your OS:

    - **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
    - **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
    - **Linux:** `~/.config/Claude/claude_desktop_config.json`

    ```json
    {
      "mcpServers": {
        "dataviz-mcp": {
          "command": "/path/to/pls",
          "args": ["mcp"]
        }
      }
    }
    ```

    !!! warning "Use your absolute path"
        Replace `"command": "/path/to/pls"` with the path printed above,
        e.g. `"command": "/path/to/dataviz-mcp/.venv/bin/pls"`

    Restart Claude Desktop.

=== "Claude Code"

    ```bash
    claude mcp add dataviz-mcp -- /path/to/pls mcp
    ```

    !!! warning "Use your absolute path"
        Replace `/path/to/pls` with the path printed above,
        e.g. `claude mcp add dataviz-mcp -- /path/to/dataviz-mcp/.venv/bin/pls mcp`

=== "claude.ai"

    claude.ai requires HTTP transport and a public URL. You can use any tunneling service
    (ngrok, Cloudflare, localhost.run, etc.); this example uses Cloudflare.

    **Terminal 1**: start the MCP server:

    ```bash
    /path/to/pls mcp --transport http --port 8001
    ```

    !!! warning "Use your absolute path"
        Replace `/path/to/pls` with the path printed above,
        e.g. `/path/to/dataviz-mcp/.venv/bin/pls mcp --transport http --port 8001`

    **Terminal 2**: tunnel for the MCP server:

    ```bash
    cloudflared tunnel --url http://localhost:8001
    ```

    **Terminal 3**: tunnel for the Panel server:

    ```bash
    cloudflared tunnel --url http://localhost:5077
    ```

    Stop Terminal 1, then set the Panel tunnel URL.

    **macOS / Linux:**

    ```bash
    export DATAVIZ_MCP_EXTERNAL_URL=<url-from-terminal-3>
    ```

    **Windows (PowerShell):**

    ```powershell
    $env:DATAVIZ_MCP_EXTERNAL_URL="<url-from-terminal-3>"
    ```

    And restart:

    ```bash
    /path/to/pls mcp --transport http --port 8001
    ```

    Then go to claude.ai → Settings → Connectors → Add custom connector and enter
    `<url-from-terminal-2>/mcp` as the URL.

---

## Step 5: Make changes and run tests

=== "pixi"

    ```bash
    pixi run test                        # run all tests
    pixi run test-coverage               # tests + coverage report
    pixi run lint                        # lint (pre-commit on all files)
    ```

=== "uv"

    ```bash
    pytest tests/                        # run all tests
    pytest tests/test_validation.py      # run a single file
    pre-commit run --all-files           # lint
    ```

---

## Step 6: Submit a pull request

1. Commit your changes:

```bash
git commit -m 'Add some feature'
```

2. Push to your fork:

```bash
git push origin feature/YourFeature
```

3. Open a pull request against the `main` branch on GitHub.

Please ensure your code passes all tests and linting before submitting.
