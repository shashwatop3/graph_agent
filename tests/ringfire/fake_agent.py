"""A stand-in for a language model that behaves like a simple, honest agent. No provider needed.

Each turn it reads the context it is shown, tells both ring neighbours about every belief it has
not yet passed to them, and waters when its own field is due to catch fire today. It makes one tool
call per model step, like a real model would, then says it is done.

The plan for a turn is made once, on the turn's first step, and then followed. (Planning again on
every step would not work: "already sent" is recorded while planning.)
"""

import re

from probe_answer import is_probe, probe_answer

from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall

BELIEF = re.compile(r"\[(B\d+) (?:active|suspect) [^\]]*\] fire reaches (F\d+) on day (\d+)")


def honest_agent(n_agents: int) -> ScriptedModel:
    already_sent: set[tuple] = set()  # (agent, belief, neighbour): each is passed on once
    plans: dict[tuple[int, int], list[ToolCall]] = {}  # (agent, day) -> this turn's tool calls

    def make_plan(context: str, me: int, day: int) -> list[ToolCall]:
        plan = []
        for belief_id, field, due in BELIEF.findall(context.partition("## Beliefs")[2]):
            if field == f"F{me}" and int(due) == day:
                plan.append(ToolCall("act", {"type": "water", "target": field}, f"w{len(plan)}"))
            for neighbour in ((me - 1) % n_agents, (me + 1) % n_agents):
                key = (me, belief_id, neighbour)
                if key not in already_sent:
                    already_sent.add(key)
                    call = {"to": f"A{neighbour}", "belief_id": belief_id}
                    plan.append(ToolCall("send", call, f"s{len(plan)}"))
        return plan

    def policy(system, messages, tools):
        first = messages[0]["content"]
        if is_probe(first):  # a question, not a turn: just answer it
            return ModelReply(text=probe_answer(first, n_agents), tokens_in=len(first) // 4)
        me = int(re.search(r"You are A(\d+)", first).group(1))
        day = int(re.search(r"It is day (\d+)", first).group(1))
        done = sum(m["role"] == "tool" for m in messages)
        if done == 0:
            plans[(me, day)] = make_plan(first, me, day)
        plan = plans[(me, day)]
        if done < len(plan):
            return ModelReply(tool_calls=[plan[done]], tokens_in=len(first) // 4, tokens_out=20)
        return ModelReply(text="done for today", tokens_in=len(first) // 4, tokens_out=5)

    return ScriptedModel(policy)
