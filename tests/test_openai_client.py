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
