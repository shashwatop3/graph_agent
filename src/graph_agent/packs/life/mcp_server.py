"""The simulated services as a real MCP server.

    uv run python -m graph_agent.packs.life.mcp_server        # serve a fresh week over stdio

Any MCP client can use it: Claude Desktop, Claude Code, or the frame itself (frame/mcp.py), which
is how the tests check that nodes work the same with tools from a real MCP server as with tools
provided in-process. Read-only tools carry the readOnlyHint annotation, so the frame lets nodes
call them freely and gates the rest; checking tools return their claims as structured content.
"""

import asyncio
from typing import Any

from graph_agent.frame.tools import ToolSpec

from .tools import LifeTools
from .world import LifeWorld


def life_server(world: LifeWorld) -> Any:
    import mcp_types as types
    from mcp.server import Server

    specs: dict[str, ToolSpec] = {t.name: t for t in LifeTools(world).list_tools()}

    async def list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=spec.name,
                    description=spec.description,
                    input_schema=spec.input_schema,
                    annotations=types.ToolAnnotations(
                        read_only_hint=not spec.outward, destructive_hint=spec.outward
                    ),
                )
                for spec in specs.values()
            ]
        )

    async def call_tool(ctx: Any, params: Any) -> Any:
        spec = specs.get(params.name)
        if spec is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"unknown tool {params.name}")],
                is_error=True,
            )
        arguments: dict[str, Any] = dict(params.arguments or {})
        try:
            text = spec.handler(arguments)
        except (ValueError, KeyError) as error:
            return types.CallToolResult(
                content=[
                    types.TextContent(type="text", text=str(error.args[0] if error.args else error))
                ],
                is_error=True,
            )
        structured: dict[str, Any] | None = None
        if spec.observes is not None:
            structured = {"claims": [list(c) for c in spec.observes(arguments, text)]}
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)], structured_content=structured
        )

    return Server("life-services", on_list_tools=list_tools, on_call_tool=call_tool)


async def _serve() -> None:
    from mcp.server.stdio import stdio_server

    server = life_server(LifeWorld())
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()


__all__ = ["life_server", "main"]
