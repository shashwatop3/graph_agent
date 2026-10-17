"""A stand-in for a Ring Fire agent: simple and honest, no provider needed (the console's free
demo; the tests keep their own copy, which also answers probes).

Each turn it reads the context it is shown, tells both ring neighbours about every belief it has
not yet passed to them, and waters when its own field is due to catch fire today. It makes one tool
call per model step, like a real model would, then says it is done.

With the linear fire (its context lists "Your fields this morning") it decides about water first,
as the rules ask: it waters while its own field burns or when fire is due there today, and waits
otherwise; then it passes beliefs on.
"""

import re

from graph_agent.harness.llm import ChatMessage, ModelReply, ScriptedModel, ToolCall, ToolSchema

BELIEF = re.compile(r"\[(B\d+) (?:active|suspect)[^\]]*\] fire reaches (F\d+) on day (\d+)")


def honest_agent(n_agents: int) -> ScriptedModel:
    already_sent: set[tuple[int, str, int]] = set()  # (agent, belief, neighbour)
    plans: dict[tuple[int, int], list[ToolCall]] = {}  # (agent, day) -> this turn's tool calls

    def make_plan(context: str, me: int, day: int) -> list[ToolCall]:
        plan: list[ToolCall] = []
        beliefs = BELIEF.findall(context.partition("## Beliefs")[2])
        if "## Your fields this morning" in context:
            burning = f"F{me}: burning" in context.partition("## Your fields this morning")[2]
            due = any(field == f"F{me}" and int(d) == day for _, field, d in beliefs)
            choice = "water" if burning or due else "wait"
            plan.append(ToolCall("act", {"type": choice, "target": f"F{me}"}, "w0"))
            beliefs_to_water: list[tuple[str, str, str]] = []
        else:
            beliefs_to_water = beliefs
        for _, field, due in beliefs_to_water:
            if field == f"F{me}" and int(due) == day:
                plan.append(ToolCall("act", {"type": "water", "target": field}, f"w{len(plan)}"))
        for belief_id, _field, _due in beliefs:
            for neighbour in ((me - 1) % n_agents, (me + 1) % n_agents):
                key = (me, belief_id, neighbour)
                if key not in already_sent:
                    already_sent.add(key)
                    call = {"to": f"A{neighbour}", "belief_id": belief_id}
                    plan.append(ToolCall("send", dict(call), f"s{len(plan)}"))
        return plan

    def policy(system: str, messages: list[ChatMessage], tools: list[ToolSchema]) -> ModelReply:
        first = messages[0]["content"]
        who = re.search(r"You are A(\d+)", first)
        when = re.search(r"It is day (\d+)", first)
        if who is None or when is None:
            return ModelReply(text="done")
        me, day = int(who.group(1)), int(when.group(1))
        done = sum(m["role"] == "tool" for m in messages)
        if done == 0:
            plans[(me, day)] = make_plan(first, me, day)
        plan = plans[(me, day)]
        if done < len(plan):
            return ModelReply(tool_calls=[plan[done]], tokens_in=len(first) // 4, tokens_out=20)
        return ModelReply(text="done for today", tokens_in=len(first) // 4, tokens_out=5)

    return ScriptedModel(policy, model="ringfire-stand-in")
