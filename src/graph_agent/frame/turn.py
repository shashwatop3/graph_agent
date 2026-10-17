"""One model node's turn: show it its compiled context, let it call tools until it is done.

The same loop as harness/agent.py, over a ToolSet instead of a bare toolbox, so a node can have its
own tools beside the graph tools. With only the graph tools it sends the model exactly what the
original loop sends, so the two give identical runs (and share a model cache).
"""

from collections.abc import Callable

from ..core.compiler import estimate_tokens
from ..harness.agent import SYSTEM_PROMPT, TurnResult
from ..harness.llm import ChatMessage, Json, ModelClient
from ..harness.trace import NO_TRACE, Trace
from .tools import ToolSet

__all__ = ["SYSTEM_PROMPT", "OnCall", "TurnResult", "run_node_turn"]

# (tool, arguments, result, the model's text alongside the call)
OnCall = Callable[[str, dict[str, Json], str, str], None]


def run_node_turn(
    client: ModelClient,
    tools: ToolSet,
    context: str,
    max_steps: int = 6,
    trace: Trace = NO_TRACE,
    system: str = SYSTEM_PROMPT,
    on_call: OnCall | None = None,
) -> TurnResult:
    schemas = tools.schemas()
    messages: list[ChatMessage] = [{"role": "user", "content": context}]
    result = TurnResult()
    for step in range(1, max_steps + 1):
        trace.bind(step=step)
        reply = client.complete(system, messages, schemas)
        result.steps += 1
        # tokens are the provider's count when it gives one, else an estimate of what was sent
        result.tokens_in += reply.tokens_in or estimate_tokens(context)
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
            output = tools.call(call.name, call.arguments)
            result.calls.append((call.name, call.arguments, output))
            trace.emit(
                "tool_result",
                tool=call.name,
                arguments=call.arguments,
                result=output,
                error=output.startswith("error"),
            )
            if on_call is not None:
                on_call(call.name, call.arguments, output, reply.text)
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "name": call.name, "content": output}
            )
    else:
        result.hit_step_cap = True
    trace.unbind("step")
    return result
