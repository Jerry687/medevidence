"""Read-only MCP delivery adapter over the research application boundary."""

from .server import create_mcp_server

__all__ = ["create_mcp_server"]
