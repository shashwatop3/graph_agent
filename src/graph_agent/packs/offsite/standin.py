"""A stand-in for the offsite desks' models: each desk follows its role card literally. No model,
no cost: the console's free demo, and the tests' deterministic team.

It reads only the context it is sent (the compiled graph), so it shows what the graph gives a
careful desk: when the date moves, exactly the plans and actions resting on it are flagged; when
Dev drops out, exactly Dev's branch; when the look-alike is exposed, what only it said is gone and
what the venue also said stays. Each turn is a small script (a generator) that yields tool calls
and reads their results, like the life pack's stand-in.
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
from .world import FINANCE, MEAL, PEOPLE, TRAVEL_AT, day_before

LINE = re.compile(r"^\[(B\d+) (active|suspect) routes \d+ conf [\d.]+\] (.+?)   (.+)$")
ACTION = re.compile(
    r"^- (P\d+) (\w+)\((.*?)\) resting on (.*?): (\w+)(?: -> (.*?))?(\. HELD: .*)?$"
)


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    found: list[tuple[str, re.Pattern[str]]] = []
    # templates that start with the subject ("{subject}: {value}") match almost anything: last
    for predicate, template in sorted(TEMPLATES.items(), key=lambda t: t[1].startswith("{")):
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
                # templates without a subject ("the offsite is on {value}") are about the offsite
                subject = m.groupdict().get("subject") or "offsite"
                found.append(Seen(belief_id, status, predicate, subject, m["value"], via))
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


def active(seen: list[Seen], predicate: str, subject: str | None = None) -> list[Seen]:
    return [
        b
        for b in seen
        if b.predicate == predicate
        and b.status == "active"
        and (subject is None or b.subject == subject)
    ]


def one(seen: list[Seen], predicate: str, subject: str | None = None) -> Seen | None:
    found = active(seen, predicate, subject)
    return found[0] if found else None


Script = Generator[ToolCall, str, None]


def call(name: str, **arguments: Json) -> ToolCall:
    return ToolCall(name, dict(arguments), f"c-{name}")


def recorded(result: str) -> str:
    return result.split()[-1]


def retract_suspect(seen: list[Seen], *predicates: str) -> Script:
    for b in seen:
        if b.predicate in predicates and b.status == "suspect":
            yield call("retract", belief_id=b.id, reason="what it rested on changed")


def plan(
    seen: list[Seen], subject: str, predicate: str, value: str, basis: list[Json], to: list[str]
) -> Script:
    """Record a plan and send it, unless the same plan is already live."""
    if any(b.value == value for b in active(seen, predicate, subject)):
        return
    for old in active(seen, predicate, subject):  # a live plan that now says otherwise
        yield call("retract", belief_id=old.id, reason="replaced")
    result = yield call(
        "assert_belief", subject=subject, predicate=predicate, value=value, depends_on=basis
    )
    for peer in to:
        yield call("send", to=peer, belief_id=recorded(result))


def attending(seen: list[Seen]) -> dict[str, Seen]:
    """Each person's live answer (the first one shown)."""
    found: dict[str, Seen] = {}
    for b in active(seen, "attendance.status"):
        found.setdefault(b.subject.removeprefix("rsvp-"), b)
    return found


# ---- the desks ----------------------------------------------------------------------------------


def venue(context: str) -> Script:
    seen = beliefs(context)
    claims = active(seen, "booking.deposit_due") + active(seen, "booking.max_rooms")
    if any(b.told and b.value not in ("0.0", "8") for b in claims):
        yield call("venue_booking")
    yield from retract_suspect(seen, "plan.rooms", "plan.catering", "plan.invite")
    date, rate = one(seen, "offsite.date"), one(seen, "offsite.room_rate")
    for fact in (date, rate):
        if fact is not None:
            for peer in ("travel", "budget"):
                yield call("send", to=peer, belief_id=fact.id)  # a repeat is refused: harmless
    headcount = one(seen, "plan.headcount")
    if date is None or headcount is None:
        return
    n, _, names = headcount.value.partition(": ")
    basis: list[Json] = [date.id, headcount.id]
    night = day_before(date.value)
    yield from plan(seen, "offsite", "plan.rooms", f"{n} rooms, {night} night", basis, ["actions"])
    yield from plan(
        seen, "offsite", "plan.catering", f"{n} meals, {date.value}", basis, ["actions"]
    )
    yield from plan(seen, "offsite", "plan.invite", f"{date.value}: {names}", basis, ["actions"])


def people(context: str) -> Script:
    seen = beliefs(context)
    yield from retract_suspect(seen, "plan.headcount")
    answers = attending(seen)
    for answer in answers.values():
        yield call("send", to="agenda", belief_id=answer.id)  # a repeat is refused: harmless
    if set(answers) != set(PEOPLE):
        return
    coming = [p for p in PEOPLE if answers[p].value == "yes"]
    value = f"{len(coming)}: {', '.join(coming)}"
    basis: list[Json] = [answers[p].id for p in PEOPLE]
    yield from plan(seen, "offsite", "plan.headcount", value, basis, ["venue", "budget"])


def travel(context: str) -> Script:
    seen = beliefs(context)
    answers = attending(seen)
    for b in seen:
        if b.predicate == "plan.travel" and b.status == "suspect":
            yield call("retract", belief_id=b.id, reason="what it rested on changed")
        elif b.predicate == "plan.travel" and answers.get(b.subject, b).value == "no":
            yield call("retract", belief_id=b.id, reason="they are not coming")
    date = one(seen, "offsite.date")
    if date is None:
        return
    for person, answer in answers.items():
        city = one(seen, "person.city", person)
        if answer.value != "yes" or city is None:
            continue
        value = f"{day_before(date.value)} {TRAVEL_AT} from {city.value}"
        basis: list[Json] = [date.id, answer.id, city.id]
        yield from plan(seen, person, "plan.travel", value, basis, ["actions", "budget"])


def agenda(context: str) -> Script:
    seen = beliefs(context)
    answers = attending(seen)
    for owner in active(seen, "session.owner"):
        answer = answers.get(owner.value)
        if answer is not None and answer.value == "no":
            basis: list[Json] = [owner.id, answer.id]
            yield from plan(seen, owner.subject, "plan.session_owner", "me", basis, ["actions"])


def budget(context: str) -> Script:
    seen = beliefs(context)
    yield from retract_suspect(seen, "plan.budget")
    headcount, rate = one(seen, "plan.headcount"), one(seen, "offsite.room_rate")
    if headcount is None or rate is None:
        return
    n, _, names = headcount.value.partition(": ")
    coming = names.split(", ")
    trips = {p: one(seen, "plan.travel", p) for p in coming}
    if any(t is None for t in trips.values()):
        return
    fares = yield call("fares")
    table = {city: int(fare) for city, fare in re.findall(r'"(\w+)": (\d+)', fares)}
    total = sum(table[t.value.split(" from ")[1]] for t in trips.values() if t)
    total += int(n) * (float(rate.value) + MEAL)
    basis: list[Json] = [*(t.id for t in trips.values() if t), headcount.id, rate.id]
    yield from plan(seen, "offsite", "plan.budget", f"{total:.0f}", basis, ["actions"])


UNDO = {
    "travel_book": "travel_cancel",
    "rooms_book": "rooms_cancel",
    "catering_order": "catering_cancel",
    "invite_send": "invite_cancel",
}
UNDO_ARG = {
    "travel_cancel": "trip_id",
    "rooms_cancel": "block_id",
    "catering_cancel": "order_id",
    "invite_cancel": "invite_id",
}


def actions_node(context: str) -> Script:
    seen = beliefs(context)
    mine = actions(context)
    for action in mine:
        undo = UNDO.get(action.tool)
        if action.held and undo and action.result:
            # "booked trip-3: ...", "ordered food-5: ...", "sent inv-7: ..."
            target = action.result.split()[1].rstrip(":")
            yield call(undo, **{UNDO_ARG[undo]: target})
    acted = {b for action in mine if action.status == "done" for b in action.basis}
    for p in seen:
        if p.status != "active" or not p.told or p.id in acted:
            continue
        v = p.value
        if p.predicate == "plan.travel":
            yield call(
                "travel_book", person=p.subject, depart=v.split(" from ")[0], depends_on=[p.id]
            )
        elif p.predicate == "plan.rooms":
            rooms, _, night = v.partition(" rooms, ")
            yield call("rooms_book", night=night.split()[0], rooms=int(rooms), depends_on=[p.id])
        elif p.predicate == "plan.catering":
            meals, _, day = v.partition(" meals, ")
            yield call("catering_order", day=day, meals=int(meals), depends_on=[p.id])
        elif p.predicate == "plan.invite":
            day, _, names = v.partition(": ")
            invited: list[Json] = list(names.split(", "))
            yield call("invite_send", day=day, attendees=invited, depends_on=[p.id])
        elif p.predicate == "plan.session_owner":
            yield call("agenda_set", session=p.subject, owner=v, depends_on=[p.id])
        elif p.predicate == "plan.budget":
            body = f"The offsite budget is now {v}."
            yield call(
                "mail_send", to=FINANCE, subject="Offsite budget", body=body, depends_on=[p.id]
            )


def _nothing(context: str) -> Script:
    yield from ()


NODES: dict[str, Callable[[str], Script]] = {
    "venue": venue,
    "people": people,
    "travel": travel,
    "agenda": agenda,
    "budget": budget,
    "actions": actions_node,
}


def offsite_team() -> ScriptedModel:
    running: dict[str, Script] = {}

    def policy(system: str, messages: list[ChatMessage], tools: list[ToolSchema]) -> ModelReply:
        first = messages[0]["content"]
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

    return ScriptedModel(policy, model="offsite-stand-in")
