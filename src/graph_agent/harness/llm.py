"""The language-model side: one small interface, a disk cache, and a stand-in for tests.

`ModelClient` is the only thing the rest of the harness knows about a model. A real provider
(chosen later) implements `complete`; tests use `ScriptedModel`, which costs nothing.

`CachedClient` wraps any client. A request it has seen before (same model, system prompt, messages
and tools) is answered from disk, so rerunning a game is free and gives identical results. That is
what makes a benchmark run reproducible and affordable. Cache files are plain JSON, one per request.
"""

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ToolCall:
    name: str
    arguments: dict
    id: str = ""  # the provider's id for the call, echoed back with the result


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0


class ModelClient(Protocol):
    model: str  # part of the cache key, so two models never share answers

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply: ...


def _reply_from_json(data: dict) -> ModelReply:
    return ModelReply(
        text=data["text"],
        tool_calls=[ToolCall(**call) for call in data["tool_calls"]],
        tokens_in=data["tokens_in"],
        tokens_out=data["tokens_out"],
    )


class CachedClient:
    """Answers repeated requests from disk. `calls_made` counts only the real ones."""

    def __init__(self, inner: ModelClient, cache_dir: str | Path):
        self.inner = inner
        self.model = inner.model
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.calls_made = 0  # requests that reached the model
        self.cache_hits = 0
        self.tokens_in = 0  # tokens actually paid for (not counting cache hits)
        self.tokens_out = 0

    def _key(self, system: str, messages: list[dict], tools: list[dict]) -> str:
        request = {"model": self.model, "system": system, "messages": messages, "tools": tools}
        blob = json.dumps(request, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply:
        path = self.cache_dir / f"{self._key(system, messages, tools)}.json"
        if path.exists():
            self.cache_hits += 1
            return _reply_from_json(json.loads(path.read_text()))
        reply = self.inner.complete(system, messages, tools)
        self.calls_made += 1
        self.tokens_in += reply.tokens_in
        self.tokens_out += reply.tokens_out
        path.write_text(json.dumps(asdict(reply), sort_keys=True))
        return reply


class ScriptedModel:
    """A stand-in model for tests: `policy(system, messages, tools)` decides every reply.

    It lets the whole harness run (context, tool calls, messages, corrections) with no provider,
    no key and no cost, and always gives the same answers.
    """

    def __init__(
        self, policy: Callable[[str, list[dict], list[dict]], ModelReply], model="scripted"
    ):
        self.policy = policy
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply:
        return self.policy(system, messages, tools)
