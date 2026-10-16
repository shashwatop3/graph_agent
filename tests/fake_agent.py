"""A stand-in for a language model that behaves like a simple, honest agent. No provider needed.

Each turn it reads the context it is shown, tells both ring neighbours about every belief it has
not yet passed to them, and waters when its own field is due to catch fire today. It makes one tool
call per model step, like a real model would, then says it is done.
"""

import re

from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall

BELIEF = re.compile(r"\[(B\d+) (?:active|suspect) [^\]]*\] fire reaches (F\d+) on day (\d+)")


def honest_agent(n_agents: int) -> ScriptedModel:
    already_sent: set[tuple] = set()  # (agent, belief, neighbour): each is passed on once

    def policy(system, messages, tools):
        first = messages[0]["content"]
        me = int(re.search(r"You are A(\d+)", first).group(1))
        day = int(re.search(r"It is day (\d+)", first).group(1))
        plan = []
        for belief_id, field, due in BELIEF.findall(first.partition("## Beliefs")[2]):
            if field == f"F{me}" and int(due) == day:
                plan.append(ToolCall("act", {"type": "water", "target": field}, f"w{len(plan)}"))
            for neighbour in ((me - 1) % n_agents, (me + 1) % n_agents):
                key = (me, belief_id, neighbour)
                if key not in already_sent:
                    already_sent.add(key)
                    call = {"to": f"A{neighbour}", "belief_id": belief_id}
                    plan.append(ToolCall("send", call, f"s{len(plan)}"))
        done = sum(m["role"] == "tool" for m in messages)
        if done < len(plan):
            return ModelReply(tool_calls=[plan[done]], tokens_in=len(first) // 4, tokens_out=20)
        return ModelReply(text="done for today", tokens_in=len(first) // 4, tokens_out=5)

    return ScriptedModel(policy)
