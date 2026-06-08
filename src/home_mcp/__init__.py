"""home-mcp: a secure, self-hosted MCP server for Docker, deploys, and the GitHub CLI.

The server speaks the Model Context Protocol over Streamable HTTP and is meant to
sit behind a TLS-terminating reverse proxy on a home server, reachable only by
Claude sessions that present a strong bearer token.
"""

__version__ = "0.1.0"

SERVER_NAME = "home-mcp"
