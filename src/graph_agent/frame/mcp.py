"""Nodes' own tools from a real MCP server: any server, over stdio, HTTP, or in-process.

    tools = MCPTools(StdioServerParameters(command="uvx", args=["some-mcp-server"]))
    runtime.providers.append(tools)        # nodes now see its tools, filtered by their spec
    ...
    tools.close()

The frame runs synchronously, so the MCP client lives on its own event loop in a background thread
and each call waits for its answer.

How a server's tools are treated:
  * outward: a tool is gated (depends_on, approval) unless the server marks it read-only
    (the `readOnlyHint` annotation). Unknown means gated: least privilege.
  * evidence: a result whose structured content has "claims" ([[subject, predicate, value], ...])
    is recorded as evidence for the caller, like a checking tool.

Needs the optional extra: `uv sync --extra service` (the `mcp` package).
"""

import asyncio
import fnmatch
import json
import threading
from collections.abc import Coroutine, Sequence
from typing import Any, cast

from ..harness.llm import Json
from .tools import ToolSpec


class MCPTools:
    def __init__(
        self,
        server: Any,
        *,
        prefix: str = "",
        timeout: float = 60.0,
        bind: dict[str, Any] | None = None,
        include: Sequence[str] | None = None,
        exclude: Sequence[str] = (),
    ):
        """`bind`: arguments filled in on every call and hidden from the model (a server that
        wants the account's email on each tool). `include` and `exclude`: tool names (patterns
        such as "find-*") to offer; with neither, every tool the server lists."""
        from mcp import Client  # the optional extra, imported only when used

        self.prefix = prefix
        self.bind = dict(bind or {})
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._client = Client(server)
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._failure: BaseException | None = None
        # the client is entered and exited in one task, as its cancel scopes require
        self._session = asyncio.run_coroutine_threadsafe(self._hold(), self._loop)
        if not self._ready.wait(timeout) or self._failure is not None:
            raise RuntimeError(f"could not connect to the MCP server: {self._failure}")
        listed = self._run(self._client.list_tools())
        self._tools = [
            self._spec(tool)
            for tool in listed.tools
            if (include is None or any(fnmatch.fnmatchcase(tool.name, p) for p in include))
            and not any(fnmatch.fnmatchcase(tool.name, p) for p in exclude)
        ]

    async def _hold(self) -> None:
        self._stop = asyncio.Event()
        try:
            async with self._client:
                self._ready.set()
                await self._stop.wait()
        except BaseException as error:
            self._failure = error
            self._ready.set()
            raise

    def _run[T](self, coroutine: Coroutine[Any, Any, T]) -> T:
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result(self.timeout)

    def _spec(self, tool: Any) -> ToolSpec:
        annotations = getattr(tool, "annotations", None)
        read_only = bool(annotations is not None and getattr(annotations, "read_only_hint", False))
        name = str(tool.name)
        schema: dict[str, Json] = dict(tool.input_schema or {"type": "object", "properties": {}})
        if self.bind:  # the model never sees (or has to supply) what is bound
            given = schema.get("properties")
            if isinstance(given, dict):
                schema["properties"] = {k: v for k, v in given.items() if k not in self.bind}
            required = schema.get("required")
            if isinstance(required, list):
                schema["required"] = [r for r in required if r not in self.bind]
        claims: dict[str, list[tuple[str, str, Any]]] = {}

        def handler(arguments: dict[str, Any]) -> str:
            result = self._run(self._client.call_tool(name, {**arguments, **self.bind}))
            text = "\n".join(
                str(getattr(block, "text", ""))
                for block in result.content
                if hasattr(block, "text")
            )
            if result.is_error:
                raise ValueError(text or f"{name} failed")
            structured = cast(dict[str, Any], result.structured_content or {})
            found = structured.get("claims")
            rows = cast(list[Any], found) if isinstance(found, list) else []
            claims["last"] = [
                (str(row[0]), str(row[1]), row[2])
                for row in (cast(list[Any], r) for r in rows if isinstance(r, list))
                if len(row) == 3
            ]
            return text or json.dumps(structured)

        def observes(arguments: dict[str, Any], result: str) -> list[tuple[str, str, Any]]:
            return claims.pop("last", [])

        return ToolSpec(
            name=f"{self.prefix}{name}",
            description=str(tool.description or name),
            input_schema=schema,
            handler=handler,
            outward=not read_only,
            observes=observes if read_only else None,
        )

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        """Call one tool directly (not through a model), with the bound arguments added. Raises
        ValueError with the server's message if it refuses."""
        for tool in self._tools:
            if tool.name == f"{self.prefix}{name}":
                return tool.handler(dict(arguments or {}))
        raise ValueError(f"the server offers no tool {name!r}")

    def close(self) -> None:
        stop = self._stop
        if stop is not None:
            self._loop.call_soon_threadsafe(stop.set)
            try:
                self._session.result(self.timeout)
            finally:
                self._loop.call_soon_threadsafe(self._loop.stop)
                self._thread.join(timeout=5)
