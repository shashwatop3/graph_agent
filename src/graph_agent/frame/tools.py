"""The tools a node can call: the shared graph tools, plus its own tools, shaped like MCP tools.

Every agent node gets the shared graph tools (recall, explain, assert_belief, send, ...: the core
Toolbox) and the frame's extra graph tools if its spec asks for them. On top of that it gets its own
tools, which come from providers: the environment of a game, a simulated mailbox, or a real MCP
server. A node only sees the tools its spec allows (`tools`, with "mail.*" allowing a group).

A tool is described the way MCP describes one (a name, a description, a JSON schema for the
arguments), so a provider backed by a real MCP server and one written in Python look the same.
"""

import fnmatch
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from ..core.tools import TOOL_NAMES, Toolbox
from ..harness.agent import tool_schemas
from ..harness.llm import Json, ToolSchema

ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolSpec:
    """One tool, as MCP lists it. `handler` gets the arguments and returns text for the model; it
    raises ValueError (or KeyError) to refuse, which the model reads as an "error:" line."""

    name: str
    description: str
    input_schema: dict[str, Json]
    handler: ToolHandler
    outward: bool = False  # it changes something outside the graph (sends, pays, books): gated
    # a checking tool: (arguments, result) -> the claims its result establishes, recorded as
    # evidence for the node that called it (so the checker can test what it was told)
    observes: Callable[[dict[str, Any], str], list[tuple[str, str, Any]]] | None = None
    # an outward tool: (arguments, result) -> the claims it makes true once carried out. A later
    # check that reads one back is the team's own doing, so it confirms the action, not holds it
    effects: Callable[[dict[str, Any], str], list[tuple[str, str, Any]]] | None = None

    def schema(self) -> ToolSchema:
        return {"name": self.name, "description": self.description, "parameters": self.input_schema}


class ToolProvider(Protocol):
    """Anything that offers tools: an environment, a simulated service, an MCP client.

    A provider may also define `tools_for_node(node_id) -> list[ToolSpec]`: the tools as one node
    gets them, for a tool whose answer depends on who asks (the runtime uses it when present)."""

    def list_tools(self) -> list[ToolSpec]: ...


def allowed(name: str, patterns: Sequence[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


def schema_of(properties: dict[str, Json], required: Sequence[str] = ()) -> dict[str, Json]:
    """A JSON schema for an object with these properties (a small helper for tool authors)."""
    return {"type": "object", "properties": properties, "required": list(required)}


class ToolSet:
    """One node's tools for one turn: the graph toolbox, then its own tools, in that order.

    `names`, `schemas()` and `call()` are all the turn loop needs. The graph tools keep exactly the
    names, descriptions and schemas of the core Toolbox, so a node on the frame is shown the same
    tools as an agent in the original game loop.
    """

    def __init__(
        self,
        box: Toolbox,
        graph_tools: Sequence[str] | None = None,
        extra: Sequence[ToolSpec] = (),
    ):
        self.box = box
        self.graph_names = [n for n in TOOL_NAMES if graph_tools is None or n in graph_tools]
        self.extra = {t.name: t for t in extra}
        self.names = [*self.graph_names, *self.extra]

    @property
    def now(self) -> int:
        return self.box.now

    @now.setter
    def now(self, tick: int) -> None:
        self.box.now = tick

    def schemas(self) -> list[ToolSchema]:
        graph = [s for s in tool_schemas(self.box) if s["name"] in self.graph_names]
        return [*graph, *(t.schema() for t in self.extra.values())]

    def call(self, name: str, arguments: dict[str, Json]) -> str:
        if name not in self.names:
            return f"error: unknown tool {name!r}; the tools are {', '.join(self.names)}"
        if name in self.extra:
            try:
                return self.extra[name].handler(dict(arguments))
            except (ValueError, KeyError) as error:
                return f"error: {error.args[0] if error.args else error}"
            except TypeError as error:
                return f"error: bad arguments for {name}: {error}"
        try:
            return getattr(self.box, name)(**arguments)
        except TypeError as error:  # wrong or missing arguments
            return f"error: bad arguments for {name}: {error}"
