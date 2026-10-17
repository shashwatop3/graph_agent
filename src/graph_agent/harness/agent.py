"""One agent's turn: show it its context, let it call tools until it is done.

The loop is deliberately plain. The model sees the compiled context, may call tools (each one is
executed against the agent's own toolbox and the result goes back to it), and its turn ends when it
replies without calling a tool or after `max_steps` rounds. Nothing carries over between turns
except what the agent wrote into the store, because the next context is compiled from the store.
"""

import inspect
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol, get_type_hints

from pydantic import TypeAdapter

from ..core.compiler import estimate_tokens
from .llm import ChatMessage, Json, ModelClient, ToolSchema
from .trace import NO_TRACE, Trace

SYSTEM_PROMPT = (
    "You are one agent in a multi-agent game. You act only by calling tools. Read your situation, "
    "call the tools you need, and when you are finished for today reply with a short sentence and "
    "no tool call. Do not repeat a tool call that already succeeded."
)


class Tools(Protocol):
    """One agent's tools for one turn. The loop shows the model `names` and calls them by name."""

    now: int

    @property
    def names(self) -> Sequence[str]: ...


def tool_schemas(box: Tools) -> list[ToolSchema]:
    """The tools `box` offers, as JSON schemas built from its method signatures and docstrings."""
    schemas: list[ToolSchema] = []
    for name in box.names:
        method = getattr(type(box), name)
        hints = get_type_hints(method)
        properties: dict[str, Json] = {}
        required: list[Json] = []
        for parameter in list(inspect.signature(method).parameters.values())[1:]:  # skip self
            properties[parameter.name] = TypeAdapter(hints[parameter.name]).json_schema()
            if parameter.default is inspect.Parameter.empty:
                required.append(parameter.name)
        schemas.append(
            {
                "name": name,
                "description": inspect.getdoc(method),
                "parameters": {"type": "object", "properties": properties, "required": required},
            }
        )
    return schemas


@dataclass
class TurnResult:
    # (tool, arguments, result)
    calls: list[tuple[str, dict[str, Json], str]] = field(
        default_factory=list[tuple[str, dict[str, Json], str]]
    )
    final_text: str = ""
    steps: int = 0
    hit_step_cap: bool = False  # still calling tools when it ran out of steps
    tokens_in: int = 0
    tokens_cached: int = 0  # of tokens_in, read from the provider's prompt cache
    tokens_out: int = 0


def call_tool(box: Tools, name: str, arguments: dict[str, Json]) -> str:
    if name not in box.names:
        return f"error: unknown tool {name!r}; the tools are {', '.join(box.names)}"
    try:
        return getattr(box, name)(**arguments)
    except TypeError as error:  # wrong or missing arguments
        return f"error: bad arguments for {name}: {error}"


def run_turn(
    client: ModelClient,
    box: Tools,
    context: str,
    max_steps: int = 6,
    trace: Trace = NO_TRACE,
) -> TurnResult:
    schemas = tool_schemas(box)
    messages: list[ChatMessage] = [{"role": "user", "content": context}]
    result = TurnResult()
    for step in range(1, max_steps + 1):
        trace.bind(step=step)
        reply = client.complete(SYSTEM_PROMPT, messages, schemas)
        result.steps += 1
        # tokens are the provider's count when it gives one, else an estimate of what was sent
        result.tokens_in += reply.tokens_in or estimate_tokens(context)
        result.tokens_cached += reply.tokens_cached
        result.tokens_out += reply.tokens_out
        if not reply.tool_calls:
            result.final_text = reply.text
            break
        messages.append(
            {
                "role": "assistant",
                "content": reply.text,
                "tool_calls": [
                    {"id": c.id, "name": c.name, "arguments": c.arguments} for c in reply.tool_calls
                ],
            }
        )
        for call in reply.tool_calls:  # in the order the model gave them: deterministic
            output = call_tool(box, call.name, call.arguments)
            result.calls.append((call.name, call.arguments, output))
            trace.emit(
                "tool_result",
                tool=call.name,
                arguments=call.arguments,
                result=output,
                error=output.startswith("error"),
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": output}
            )
    else:
        result.hit_step_cap = True
    trace.unbind("step")
    return result
