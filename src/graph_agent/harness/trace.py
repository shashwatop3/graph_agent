"""A detailed run log, one JSON object per line, for working out afterwards what went wrong.

Every event has a time `t` (seconds since the log was opened), a `kind`, and whatever the run was
bound to at that moment (`day`, `agent`). The events, roughly in the order they happen:

    game_start     the scenario, the system, the model
    day_start      a day begins; the scripted lies go out
    turn_start     what one agent reads (the full compiled context) before it acts
    model_call     one request to the model: text, tool calls, tokens, seconds, cached or not
    tool_result    one tool call and exactly what the tool answered
    action         what the game did with a water or link action
    message        a message delivered (or held until the day's turns are over)
    imposter_relay an imposter passing a message on
    turn_end       steps, tokens, whether the turn ran out of steps
    day_end        what the engine reported (fires, burnt out, watered), who was newly distrusted
    exposure       one agent stopped trusting another, and which beliefs that changed
    probe          a probe question and the answer
    beliefs        at the end, every arrival belief an agent holds, next to the truth
    score          the final score row

`NO_TRACE` is a trace that records nothing, so callers that do not want a log pass nothing.
Read a log with `benchmarks/inspect_log.py`.
"""

import json
import time
from pathlib import Path
from typing import IO

from .llm import ChatMessage, ModelClient, ModelReply, ToolSchema


class Trace:
    def __init__(self, path: str | Path | None = None, *, contexts: bool = True):
        self.contexts = contexts  # log the full text each agent reads (the bulk of a log)
        self._file: IO[str] | None = None
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._file = Path(path).open("w")
        self._start = time.monotonic()
        self._bound: dict[str, object] = {}

    @property
    def enabled(self) -> bool:
        return self._file is not None

    def bind(self, **fields: object) -> None:
        """Add these fields to every event until `unbind`."""
        self._bound.update(fields)

    def unbind(self, *names: str) -> None:
        for name in names:
            self._bound.pop(name, None)

    def emit(self, kind: str, **fields: object) -> None:
        if self._file is None:
            return
        record = {"t": round(time.monotonic() - self._start, 3), "kind": kind, **self._bound}
        record.update(fields)
        self._file.write(json.dumps(record, default=str) + "\n")
        self._file.flush()  # a crashed run still leaves its log

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


NO_TRACE = Trace()


class TracedClient:
    """Wraps a model client and logs every request it answers. `cache_hits` is read from the inner
    client when it has one, to tell a cached answer from a paid one."""

    def __init__(self, inner: ModelClient, trace: Trace):
        self.inner = inner
        self.trace = trace
        self.model = inner.model

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply:
        hits_before = getattr(self.inner, "cache_hits", None)
        started = time.monotonic()
        try:
            reply = self.inner.complete(system, messages, tools)
        except Exception as error:
            self.trace.emit("model_error", error=f"{type(error).__name__}: {error}")
            raise
        self.trace.emit(
            "model_call",
            seconds=round(time.monotonic() - started, 3),
            cached=hits_before is not None and getattr(self.inner, "cache_hits", 0) > hits_before,
            n_messages=len(messages),
            text=reply.text,
            tool_calls=[{"name": c.name, "arguments": c.arguments} for c in reply.tool_calls],
            tokens_in=reply.tokens_in,
            tokens_out=reply.tokens_out,
        )
        return reply
