"""Configured read-only stdio MCP entry point over the local application."""

from __future__ import annotations

import asyncio


async def _main() -> None:
    from mcp.server.stdio import stdio_server

    from medevidence.infrastructure.local_runtime_settings import LocalRuntimeSettings
    from medevidence.local_runtime import open_local_application
    from medevidence.mcp_server.server import create_mcp_server

    with open_local_application(LocalRuntimeSettings.from_env()) as application:
        server = create_mcp_server(application)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_main())
