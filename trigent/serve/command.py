"""Serve command implementation."""

from trigent.serve.mcp_server import run_mcp_server


def serve_repository(repo: str, host: str, port: int, config: dict) -> None:
    """Start MCP server for a repository."""
    print(f"🚀 Starting MCP server for {repo}")
    run_mcp_server(host=host, port=port, repo=repo, config=config)
