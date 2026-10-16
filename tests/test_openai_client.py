"""The real-model client, tested without a server: `_post` is replaced by a canned reply."""

import json

from graph_agent.harness.llm import OpenAICompatibleClient


def client_replying(reply, seen):
    client = OpenAICompatibleClient("m")
    client._post = lambda body: (seen.append(body), reply)[1]
    return client


def test_a_tool_call_is_parsed_and_arguments_become_a_dict():
    reply = {
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {"id": "x1", "function": {"name": "recall", "arguments": '{"a": 1}'}}
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    seen = []
    result = client_replying(reply, seen).complete("sys", [], [{"name": "recall"}])
    assert [(c.name, c.arguments, c.id) for c in result.tool_calls] == [("recall", {"a": 1}, "x1")]
    assert (result.tokens_in, result.tokens_out) == (12, 3)
    assert seen[0]["tools"][0]["function"]["name"] == "recall"
    assert seen[0]["max_tokens"] > 0  # always capped


def test_a_malformed_arguments_string_does_not_crash():
    reply = {
        "choices": [
            {"message": {"tool_calls": [{"function": {"name": "t", "arguments": "{oops"}}]}}
        ]
    }
    result = client_replying(reply, []).complete("s", [], [])
    assert result.tool_calls[0].arguments == {} and result.tool_calls[0].id == "c0"


def test_earlier_tool_calls_are_sent_back_with_json_string_arguments():
    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "x1", "name": "recall", "arguments": {"a": 1}}],
        },
        {"role": "tool", "tool_call_id": "x1", "name": "recall", "content": "ok"},
    ]
    seen = []
    client_replying({"choices": [{"message": {"content": "done"}}]}, seen).complete(
        "sys", history, []
    )
    sent = seen[0]["messages"]
    assert sent[0] == {"role": "system", "content": "sys"}
    assert json.loads(sent[2]["tool_calls"][0]["function"]["arguments"]) == {"a": 1}
    assert "tools" not in seen[0]


# ---- the Anthropic client ----------------------------------------------------------------------


def test_anthropic_results_of_one_turn_are_merged_into_one_user_message():
    from graph_agent.harness.llm import AnthropicClient

    history = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "a", "name": "recall", "arguments": {}},
                {"id": "b", "name": "send", "arguments": {"to": "A1"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "name": "recall", "content": "r1"},
        {"role": "tool", "tool_call_id": "b", "name": "send", "content": "r2"},
    ]
    wire = AnthropicClient._wire_messages(history)
    assert [m["role"] for m in wire] == ["user", "assistant", "user"]
    assert [b["type"] for b in wire[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in wire[2]["content"]] == ["a", "b"]


def test_anthropic_reply_is_parsed():
    from graph_agent.harness.llm import AnthropicClient

    client = AnthropicClient(api_key="k")
    seen = []
    reply = {
        "content": [
            {"type": "text", "text": "ok"},
            {"type": "tool_use", "id": "t1", "name": "act", "input": {"type": "water"}},
        ],
        "usage": {"input_tokens": 7, "output_tokens": 2},
    }
    client._post = lambda body: (seen.append(body), reply)[1]
    result = client.complete("sys", [], [{"name": "act", "description": "d", "parameters": {}}])
    assert result.text == "ok" and result.tool_calls[0].arguments == {"type": "water"}
    assert (result.tokens_in, result.tokens_out) == (7, 2)
    assert seen[0]["system"] == "sys" and seen[0]["tools"][0]["input_schema"] == {}


def test_a_reply_cut_off_by_the_output_cap_says_so():
    reply = {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}]}
    assert client_replying(reply, []).complete("s", [], []).stop_reason == "length"


def test_the_anthropic_stop_reason_is_kept():
    from graph_agent.harness.llm import AnthropicClient

    client = AnthropicClient(api_key="k")
    reply = {"content": [{"type": "text", "text": "hi"}], "stop_reason": "max_tokens"}
    client._post = lambda body: reply
    assert client.complete("s", [], []).stop_reason == "max_tokens"
