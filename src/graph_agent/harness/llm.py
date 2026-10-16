"""The language-model side: one small interface, a disk cache, and a stand-in for tests.

`ModelClient` is the only thing the rest of the harness knows about a model. A real provider
(chosen later) implements `complete`; tests use `ScriptedModel`, which costs nothing.

`CachedClient` wraps any client. A request it has seen before (same model, system prompt, messages
and tools) is answered from disk, so rerunning a game is free and gives identical results. That is
what makes a benchmark run reproducible and affordable. Cache files are plain JSON, one per request.
"""

import hashlib
import json
import urllib.error
import urllib.request
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


def _send(request: urllib.request.Request, timeout: float) -> dict:
    """Send a request; on an HTTP error, raise it with the server's own explanation."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code}: {error.read().decode(errors='replace')[:500]}"
        ) from None


class OpenAICompatibleClient:
    """A real model behind any server that speaks the OpenAI chat API: llama.cpp's llama-server,
    Ollama (http://localhost:11434/v1), OpenRouter, and others. Only the base URL, the model name
    and the key (if the server wants one) change, so a local pilot and a paid run use this same
    class. Standard library only, so there is nothing extra to install.

    Our messages are already close to the OpenAI shape; the only translation is that a tool call's
    arguments travel as a JSON string on the wire and as a dict inside the harness.
    """

    def __init__(
        self,
        model: str,
        base_url: str = "http://127.0.0.1:18080/v1",
        api_key: str = "",
        max_tokens: int = 400,  # a hard stop, so a model that loops cannot run away
        temperature: float = 0.0,  # same request, same answer (as far as the server allows)
        timeout: float = 300,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        return _send(request, self.timeout)

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply:
        wire = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                m = {
                    "role": "assistant",
                    "content": m["content"] or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": json.dumps(c["arguments"]),
                            },
                        }
                        for c in m["tool_calls"]
                    ],
                }
            wire.append(m)
        body = {
            "model": self.model,
            "messages": wire,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        message = self._post(body)
        choice = message["choices"][0]["message"]
        calls = []
        for i, call in enumerate(choice.get("tool_calls") or []):
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:  # a malformed call: the tool will answer "bad arguments"
                arguments = {}
            calls.append(ToolCall(call["function"]["name"], arguments, call.get("id") or f"c{i}"))
        usage = message.get("usage", {})
        return ModelReply(
            text=choice.get("content") or "",
            tool_calls=calls,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )


class AnthropicClient:
    """Claude through Anthropic's own Messages API (standard library only).

    The wire format differs from the OpenAI one: the system prompt is a separate field, tools take
    an `input_schema`, an assistant's tool calls are `tool_use` blocks, and the results come back
    in ONE user message of `tool_result` blocks, so consecutive tool messages are merged here.
    """

    def __init__(
        self,
        model: str = "claude-haiku-5-5",
        api_key: str = "",
        max_tokens: int = 600,
        temperature: float = 0.0,
        timeout: float = 120,
        base_url: str = "https://api.anthropic.com/v1",
        workspace_id: str = "",  # needed only for a key that is not scoped to one workspace
    ):
        self.workspace_id = workspace_id
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/messages",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                **({"anthropic-workspace-id": self.workspace_id} if self.workspace_id else {}),
            },
        )
        return _send(request, self.timeout)

    @staticmethod
    def _wire_messages(messages: list[dict]) -> list[dict]:
        wire: list[dict] = []
        for m in messages:
            if m["role"] == "assistant":
                blocks = [{"type": "text", "text": m["content"]}] if m["content"] else []
                blocks += [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                    for c in m.get("tool_calls", [])
                ]
                wire.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                result = {"type": "tool_result", "tool_use_id": m["tool_call_id"]}
                result["content"] = m["content"]
                if wire and wire[-1]["role"] == "user" and isinstance(wire[-1]["content"], list):
                    wire[-1]["content"].append(result)  # results of one assistant turn go together
                else:
                    wire.append({"role": "user", "content": [result]})
            else:
                wire.append({"role": "user", "content": m["content"]})
        return wire

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> ModelReply:
        body = {
            "model": self.model,
            "system": system,
            "messages": self._wire_messages(messages),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]
        data = self._post(body)
        text = "".join(b["text"] for b in data["content"] if b["type"] == "text")
        calls = [
            ToolCall(b["name"], b["input"], b["id"])
            for b in data["content"]
            if b["type"] == "tool_use"
        ]
        usage = data.get("usage", {})
        return ModelReply(
            text=text,
            tool_calls=calls,
            tokens_in=usage.get("input_tokens", 0),
            tokens_out=usage.get("output_tokens", 0),
        )
