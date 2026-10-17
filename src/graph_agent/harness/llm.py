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
from typing import NotRequired, Protocol, TypedDict, cast

from pydantic import BaseModel, TypeAdapter

type Json = str | int | float | bool | None | list[Json] | dict[str, Json]


class ToolCallMessage(TypedDict):
    """A tool call as it sits in an assistant message in the conversation history."""

    id: str
    name: str
    arguments: dict[str, Json]


class ChatMessage(TypedDict):
    """One message of the conversation: `user`, `assistant` (maybe with tool calls) or `tool`."""

    role: str
    content: str
    tool_calls: NotRequired[list[ToolCallMessage]]  # on an assistant message
    tool_call_id: NotRequired[str]  # on a tool message: which call it answers
    name: NotRequired[str]  # on a tool message: which tool it was


class ToolSchema(TypedDict):
    name: str
    description: str | None
    parameters: dict[str, Json]  # JSON schema of the arguments


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Json]
    id: str = ""  # the provider's id for the call, echoed back with the result


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list[ToolCall])
    tokens_in: int = 0
    tokens_out: int = 0
    stop_reason: str = ""  # why it stopped; "max_tokens" or "length" means it was cut off
    tokens_cached: int = 0  # of tokens_in, how many were read from the provider's prompt cache


class ModelClient(Protocol):
    model: str  # part of the cache key, so two models never share answers

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply: ...


_REPLY = TypeAdapter(ModelReply)  # reads a cache file back into a ModelReply


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

    def _key(self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]) -> str:
        request = {"model": self.model, "system": system, "messages": messages, "tools": tools}
        blob = json.dumps(request, sort_keys=True, default=str).encode()
        return hashlib.sha256(blob).hexdigest()

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply:
        path = self.cache_dir / f"{self._key(system, messages, tools)}.json"
        if path.exists():
            self.cache_hits += 1
            return _REPLY.validate_json(path.read_text())
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
        self,
        policy: Callable[[str, list[ChatMessage], list[ToolSchema]], ModelReply],
        model: str = "scripted",
    ):
        self.policy = policy
        self.model = model

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply:
        return self.policy(system, messages, tools)


def _send(request: urllib.request.Request, timeout: float) -> object:
    """Send a request; on an HTTP error, raise it with the server's own explanation."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(
            f"HTTP {error.code}: {error.read().decode(errors='replace')[:500]}"
        ) from None


class _OpenAIFunction(BaseModel):
    name: str
    arguments: str | None = None


class _OpenAICall(BaseModel):
    id: str | None = None
    function: _OpenAIFunction


class _OpenAIMessage(BaseModel):
    content: str | None = None
    tool_calls: list[_OpenAICall] | None = None


class _OpenAIChoice(BaseModel):
    message: _OpenAIMessage
    finish_reason: str | None = None


class _OpenAIUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class _OpenAIResponse(BaseModel):
    choices: list[_OpenAIChoice]
    usage: _OpenAIUsage = _OpenAIUsage()


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

    def _post(self, body: dict[str, object]) -> object:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "content-type": "application/json",
                **({"authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
        )
        return _send(request, self.timeout)

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply:
        wire: list[dict[str, object]] = [{"role": "system", "content": system}]
        for m in messages:
            calls_made = m.get("tool_calls")
            if m["role"] == "assistant" and calls_made:
                wire.append(
                    {
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
                            for c in calls_made
                        ],
                    }
                )
            else:
                wire.append(dict(m))
        body: dict[str, object] = {
            "model": self.model,
            "messages": wire,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        response = _OpenAIResponse.model_validate(self._post(body))
        choice = response.choices[0].message
        calls: list[ToolCall] = []
        for i, call in enumerate(choice.tool_calls or []):
            try:
                arguments: dict[str, Json] = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:  # a malformed call: the tool will answer "bad arguments"
                arguments = {}
            calls.append(ToolCall(call.function.name, arguments, call.id or f"c{i}"))
        return ModelReply(
            text=choice.content or "",
            tool_calls=calls,
            tokens_in=response.usage.prompt_tokens,
            tokens_out=response.usage.completion_tokens,
            stop_reason=response.choices[0].finish_reason or "",
        )


class _AnthropicBlock(BaseModel):
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Json] = {}


class _AnthropicUsage(BaseModel):
    input_tokens: int = 0  # not counting what was read from or written to the prompt cache
    output_tokens: int = 0
    cache_read_input_tokens: int | None = 0
    cache_creation_input_tokens: int | None = 0


class _AnthropicResponse(BaseModel):
    content: list[_AnthropicBlock]
    stop_reason: str | None = None
    usage: _AnthropicUsage = _AnthropicUsage()


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
        temperature: float | None = None,  # newer models reject the setting, so it is optional
        timeout: float = 120,
        base_url: str = "https://api.anthropic.com/v1",
        workspace_id: str = "",  # needed only for a key that is not scoped to one workspace
        prompt_cache: bool = True,
    ):
        # Prompt caching: the tools and the conversation so far are marked as cacheable, so the
        # next model step of the same turn (and every agent's identical tools) is read from the
        # cache at a fraction of the price. A prompt shorter than the model's minimum is simply
        # not cached.
        self.prompt_cache = prompt_cache
        self.workspace_id = workspace_id
        self.model = model
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")

    def _post(self, body: dict[str, object]) -> object:
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
    def _wire_messages(messages: list[ChatMessage]) -> list[dict[str, object]]:
        wire: list[dict[str, object]] = []
        results: list[dict[str, object]] | None = None  # the open user message of tool results
        for m in messages:
            if m["role"] == "tool":
                result: dict[str, object] = {
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m["content"],
                }
                if results is not None:
                    results.append(result)  # results of one assistant turn go together
                else:
                    results = [result]
                    wire.append({"role": "user", "content": results})
                continue
            results = None
            if m["role"] == "assistant":
                blocks: list[dict[str, object]] = []
                if m["content"]:
                    blocks.append({"type": "text", "text": m["content"]})
                for c in m.get("tool_calls", []):
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": c["id"],
                            "name": c["name"],
                            "input": c["arguments"],
                        }
                    )
                wire.append({"role": "assistant", "content": blocks})
            else:
                wire.append({"role": "user", "content": m["content"]})
        return wire

    def complete(
        self, system: str, messages: list[ChatMessage], tools: list[ToolSchema]
    ) -> ModelReply:
        body: dict[str, object] = {
            "model": self.model,
            "system": system,
            "messages": self._wire_messages(messages),
            "max_tokens": self.max_tokens,
        }
        if self.temperature is not None:
            body["temperature"] = self.temperature
        if tools:
            body["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]
        if self.prompt_cache:
            _mark_cacheable(body)
        response = _AnthropicResponse.model_validate(self._post(body))
        usage = response.usage
        read = usage.cache_read_input_tokens or 0
        written = usage.cache_creation_input_tokens or 0
        return ModelReply(
            text="".join(b.text for b in response.content if b.type == "text"),
            tool_calls=[
                ToolCall(b.name, b.input, b.id) for b in response.content if b.type == "tool_use"
            ],
            tokens_in=usage.input_tokens + read + written,
            tokens_out=usage.output_tokens,
            stop_reason=response.stop_reason or "",
            tokens_cached=read,
        )


def _mark_cacheable(body: dict[str, object]) -> None:
    """Put cache breakpoints on the last tool and the last message block (Anthropic caches the
    prefix up to each breakpoint: tools, then system, then messages)."""
    ephemeral = {"type": "ephemeral"}
    tools = body.get("tools")
    if isinstance(tools, list) and tools:
        last_tool = cast(dict[str, object], tools[-1])
        last_tool["cache_control"] = ephemeral
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        return
    last = cast(dict[str, object], messages[-1])
    content = last.get("content")
    if isinstance(content, str):
        last["content"] = [{"type": "text", "text": content, "cache_control": ephemeral}]
    elif isinstance(content, list) and content:
        cast(dict[str, object], content[-1])["cache_control"] = ephemeral
