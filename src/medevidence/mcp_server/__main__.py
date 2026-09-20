"""Run the unconfigured, discovery-only MCP adapter over stdio."""

from __future__ import annotations

import asyncio

from mcp.server.stdio import stdio_server

from .server import create_mcp_server


async def _main() -> None:
    server = create_mcp_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
