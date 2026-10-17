"""A stand-in for the life team's models: each node follows its role card literally. No model,
no cost: the console's free demo, and the tests' deterministic team.

It reads only the context it is sent (the compiled graph), so it shows what the frame gives a
careful agent: when the flight moves, the plans built on it are flagged, the actions node is told
which of its actions are held, and it can put things right. Each turn is a small script (a
generator) that yields tool calls and reads their results.
"""

import re
from collections.abc import Callable, Generator
from dataclasses import dataclass

from graph_agent.harness.llm import (
    ChatMessage,
    Json,
    ModelReply,
    ScriptedModel,
    ToolCall,
    ToolSchema,
)

from .pack import TEMPLATES
from .world import minutes, when

LINE = re.compile(r"^\[(B\d+) (active|suspect) routes \d+ conf [\d.]+\] (.+?)   (.+)$")
ACTION = re.compile(
    r"^- (P\d+) (\w+)\((.*?)\) resting on (.*?): (\w+)(?: -> (.*?))?(\. HELD: .*)?$"
)


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    found: list[tuple[str, re.Pattern[str]]] = []
    for predicate, template in TEMPLATES.items():
        regex = re.escape(template).replace(r"\{subject\}", r"(?P<subject>\S+)")
        regex = regex.replace(r"\{value\}", r"(?P<value>.+)")
        found.append((predicate, re.compile(f"^{regex}$")))
    return found


PATTERNS = _patterns()


@dataclass(frozen=True)
class Seen:
    """A live belief as the context shows it."""

    id: str
    status: str
    predicate: str
    subject: str
    value: str
    via: str

    @property
    def told(self) -> bool:
        return self.via.startswith("via")


@dataclass(frozen=True)
class Act:
    """One of the node's actions, from its "Your actions" section."""

    id: str
    tool: str
    basis: tuple[str, ...]
    status: str
    result: str
    held: bool


def beliefs(context: str) -> list[Seen]:
    found: list[Seen] = []
    section = context.partition("## Beliefs\n")[2].partition("\n\n")[0]
    for line in section.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        belief_id, status, claim, via = match.groups()
        for predicate, pattern in PATTERNS:
            m = pattern.match(claim)
            if m:
                found.append(Seen(belief_id, status, predicate, m["subject"], m["value"], via))
                break
    return found


def actions(context: str) -> list[Act]:
    found: list[Act] = []
    section = context.partition("## Your actions")[2].partition("\n\n")[0]
    for line in section.splitlines()[1:]:
        m = ACTION.match(line)
        if m:
            pid, tool, _, basis, status, result, held = m.groups()
            found.append(Act(pid, tool, tuple(basis.split(", ")), status, result or "", bool(held)))
    return found


def find(
    seen: list[Seen], predicate: str, subject: str | None = None, status: str | None = None
) -> list[Seen]:
    return [
        b
        for b in seen
        if b.predicate == predicate
        and (subject is None or b.subject == subject)
        and (status is None or b.status == status)
    ]


Script = Generator[ToolCall, str, None]


def call(name: str, **arguments: Json) -> ToolCall:
    return ToolCall(name, dict(arguments), f"c-{name}")


def recorded(result: str) -> str:
    return result.split()[-1]


# ---- the nodes ----------------------------------------------------------------------------------


def travel(context: str) -> Script:
    seen = beliefs(context)
    for b in find(seen, "booking.payment_due"):
        if b.told and float(b.value) > 0:
            yield call("booking_check", ref="ABC123")
            break
    for b in seen:
        if b.predicate.startswith("plan.") and b.status == "suspect":
            yield call("retract", belief_id=b.id, reason="what it rested on changed")
    flights = find(seen, "flight.departs", "SK101", "active")
    if not flights:
        return
    flight = flights[-1]
    pickup = when(minutes(flight.value) - 210)
    block = f"{pickup}-{flight.value.split()[1]}"
    live = {b.value for b in seen if b.predicate.startswith("plan.") and b.status == "active"}
    made: list[str] = []
    for predicate, value in (("plan.cab_pickup", pickup), ("plan.travel_block", block)):
        if value not in live:
            result = yield call(
                "assert_belief",
                subject="trip-tokyo",
                predicate=predicate,
                value=value,
                depends_on=[flight.id],
            )
            made.append(recorded(result))
    for belief_id in made:
        yield call("send", to="actions", belief_id=belief_id)
        yield call("send", to="calendar", belief_id=belief_id)


def calendar(context: str) -> Script:
    seen = beliefs(context)
    for b in find(seen, "plan.event_start", status="suspect"):
        yield call("retract", belief_id=b.id, reason="the reason for the move is gone")
        event = find(seen, "event.starts", b.subject, "active")
        if event and event[0].value != b.value:
            result = yield call(
                "assert_belief",
                subject=b.subject,
                predicate="plan.event_start",
                value=event[0].value,
                depends_on=[event[0].id],
            )
            yield call("send", to="actions", belief_id=recorded(result))
        return
    moves = {b.subject for b in find(seen, "plan.event_start", status="active")}
    for block in find(seen, "plan.travel_block", "trip-tokyo", "active"):
        start, _, end = block.value.partition("-")
        lo, hi = minutes(start), minutes(f"{start.split()[0]} {end}")
        for event in find(seen, "event.starts", status="active"):
            if lo - 60 < minutes(event.value) < hi and event.subject not in moves:
                result = yield call(
                    "assert_belief",
                    subject=event.subject,
                    predicate="plan.event_start",
                    value=when(lo - 180),
                    depends_on=[block.id],
                )
                yield call("send", to="actions", belief_id=recorded(result))


def people(context: str) -> Script:
    seen = beliefs(context)
    done = {b.subject for b in find(seen, "promise.status", status="active") if b.value == "done"}
    for b in find(seen, "plan.task_due"):
        if b.status == "suspect" or b.subject in done:
            yield call("retract", belief_id=b.id, reason="the promise changed")
    planned = {
        b.subject: b.value
        for b in find(seen, "plan.task_due", status="active")
        if b.subject not in done
    }
    for due in find(seen, "promise.due", status="active"):
        if due.subject in done or planned.get(due.subject) == due.value:
            continue
        result = yield call(
            "assert_belief",
            subject=due.subject,
            predicate="plan.task_due",
            value=due.value,
            depends_on=[due.id],
        )
        yield call("send", to="actions", belief_id=recorded(result))


def money(context: str) -> Script:
    seen = beliefs(context)
    for b in find(seen, "account.status", status="active"):
        if b.told and b.value != "ok":
            yield call("account_status")
    expiring = {b.subject: b for b in find(seen, "card.expires", status="active")}
    planned = {b.subject for b in find(seen, "plan.subscription_card", status="active")}
    if planned:
        # look again at the bank's record: once actions has moved a card, this reads the team's
        # own doing back, which confirms the action instead of holding it
        yield call("subscriptions_list")
        return
    for sub in find(seen, "subscription.card", status="active"):
        if sub.value in expiring and sub.subject not in planned:
            result = yield call(
                "assert_belief",
                subject=sub.subject,
                predicate="plan.subscription_card",
                value="card-5555",
                depends_on=[sub.id, expiring[sub.value].id],
            )
            yield call("send", to="actions", belief_id=recorded(result))


def actions_node(context: str) -> Script:
    seen = beliefs(context)
    mine = actions(context)
    for action in mine:
        if not action.held:
            continue
        if action.tool == "cab_book" and "booked" in action.result:
            yield call("cab_cancel", cab_id=_word_after(action.result, "booked"))
        elif action.tool == "calendar_create" and "created" in action.result:
            yield call("calendar_delete", event_id=_word_after(action.result, "created"))
        elif action.tool == "tasks_create" and "created" in action.result:
            yield call("tasks_update", task_id=_word_after(action.result, "created"), done=True)
    acted = {basis for action in mine if not action.held for basis in action.basis}
    for plan in seen:
        if plan.status != "active" or plan.id in acted or not plan.told:
            continue
        p, v = plan.predicate, plan.value
        if p == "plan.cab_pickup":
            yield call("cab_book", pickup=v, to="LHR", depends_on=[plan.id])
        elif p == "plan.travel_block":
            start, _, end = v.partition("-")
            yield call(
                "calendar_create",
                title="Travel to the airport",
                start=start,
                end=f"{start.split()[0]} {end}",
                depends_on=[plan.id],
            )
        elif p == "plan.event_start":
            yield call(
                "calendar_move",
                event_id=plan.subject,
                start=v,
                end=when(minutes(v) + 60),
                depends_on=[plan.id],
            )
        elif p == "plan.task_due":
            yield call(
                "tasks_create",
                title=f"{plan.subject}: keep the promise",
                due=v,
                depends_on=[plan.id],
            )
        elif p == "plan.subscription_card":
            yield call(
                "subscription_set_card", subscription=plan.subject, card=v, depends_on=[plan.id]
            )


def _word_after(text: str, word: str) -> str:
    words = text.split()
    return words[words.index(word) + 1].rstrip(":")


def _nothing(context: str) -> Script:
    yield from ()


NODES: dict[str, Callable[[str], Script]] = {
    "travel": travel,
    "calendar": calendar,
    "people": people,
    "money": money,
    "actions": actions_node,
}


def life_team() -> ScriptedModel:
    running: dict[str, Script] = {}

    def policy(system: str, messages: list[ChatMessage], tools: list[ToolSchema]) -> ModelReply:
        first = messages[0]["content"]
        if "## Role" not in first:  # an extraction request: the stand-in extracts nothing
            return ModelReply(text="{}")
        found = re.search(r"You are (\w+):", first)
        me = found.group(1) if found else ""
        key = f"{me}:{hash(first)}"
        script = running.get(key)
        try:
            if script is None:
                script = NODES.get(me, _nothing)(first)
                running[key] = script
                step = next(script)
            else:
                step = script.send(messages[-1]["content"])
        except StopIteration:
            running.pop(key, None)
            return ModelReply(text="done", tokens_in=len(first) // 4, tokens_out=3)
        return ModelReply(tool_calls=[step], tokens_in=len(first) // 4, tokens_out=20)

    return ScriptedModel(policy, model="life-stand-in")
