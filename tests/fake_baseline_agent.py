"""A stand-in model for the baselines. Like fake_agent.py, but it reads a log, not a graph.

It passes on every published fact and every claim it reads to both ring neighbours (once each),
believing claims as they are, and waters when a claim says its own field catches fire today. That
is roughly what a model with only a log to go on does.
"""

import re

from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall

PUBLISHED = re.compile(r"PUBLISHED: field F(\d+) caught fire on day (\d+)")
TOLD = re.compile(r"A\d+ told A\d+ that fire reaches F(\d+) on day (\d+)")


def log_reader(n_agents: int, can_send: bool = True) -> ScriptedModel:
    already: set[tuple] = set()

    def policy(system, messages, tools):
        first = messages[0]["content"]
        me = int(re.search(r"You are A(\d+)", first).group(1))
        day = int(re.search(r"It is day (\d+)", first).group(1))
        facts = [(int(f), int(d)) for f, d in PUBLISHED.findall(first)]
        facts += [(int(f), int(d)) for f, d in TOLD.findall(first)]
        plan = []
        for field, due in facts:
            if field == me and due == day and ("water", me, day) not in already:
                already.add(("water", me, day))
                plan.append(ToolCall("act", {"type": "water"}, f"w{len(plan)}"))
            if not can_send:
                continue
            for neighbour in ((me - 1) % n_agents, (me + 1) % n_agents):
                key = (me, field, due, neighbour)
                if key not in already:
                    already.add(key)
                    call = {"to": f"A{neighbour}", "field": f"F{field}", "day": due}
                    plan.append(ToolCall("send", call, f"s{len(plan)}"))
        done = sum(m["role"] == "tool" for m in messages)
        if done < len(plan):
            return ModelReply(tool_calls=[plan[done]], tokens_in=len(first) // 4, tokens_out=20)
        return ModelReply(text="done", tokens_in=len(first) // 4, tokens_out=5)

    return ScriptedModel(policy)
