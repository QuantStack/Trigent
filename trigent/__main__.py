"""Entry point for running trigent as a module.

Supports both the main CLI and the MCP server:
- python -m trigent [...args] -> runs CLI
- python -m trigent.serve.mcp_server [...args] -> runs MCP server
"""

import sys

# Check if being run as MCP server specifically
if len(sys.argv) > 1 and sys.argv[0].endswith("mcp_server.py"):
    # Running as MCP server
    from trigent.serve.mcp_server import main as mcp_main
    if __name__ == "__main__":
        mcp_main()
else:
    # Running as main CLI
    from trigent.cli import main
    main()
