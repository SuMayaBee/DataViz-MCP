"""Tests for the DataViz MCP CLI."""

from typer.testing import CliRunner

from dataviz_mcp.cli import app

runner = CliRunner()


def test_help():
    """Test that --help works."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "DataViz MCP" in result.output


def test_serve_help():
    """Test that serve --help works."""
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "port" in result.output.lower()


def test_mcp_help():
    """Test that mcp --help works."""
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "transport" in result.output.lower()


def test_mcp_help_documents_prompt_overrides():
    """Prompt customisation is discoverable from the primary command help."""
    result = runner.invoke(app, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "--prompts" in result.output


def test_install_help_lists_supported_clients():
    """The installer is discoverable without modifying a user configuration."""
    result = runner.invoke(app, ["install", "--help"])
    assert result.exit_code == 0
    assert "claude-desktop" in result.output
