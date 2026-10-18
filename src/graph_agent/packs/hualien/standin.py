"""A stand-in for the quake desks' models: each desk follows its role card literally. No model, no
cost: the console's free demo, and the tests' deterministic team.

It reads only the context it is sent, so it shows what the frame gives a careful desk: when USGS
revises the figures, every assessment and alert built on the early ones is flagged and redone, and
a fab's own sensors expose the rumour account. Each turn is a small script (a generator) that
yields tool calls and reads their results, like the life pack's stand-in.
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

from .adapter import DEPTH, EXPOSURE, MAGNITUDE
from .pack import ALL_TEMPLATES, rank
from .world import BULLETIN, FAB_STATUS, FABS, TSUNAMI, bulletin_text

LINE = re.compile(r"^\[(B\d+) (active|suspect) routes \d+ conf [\d.]+\] (.+?)   (.+)$")
ACTION = re.compile(r"^- (P\d+) (\w+)\((.*?)\) resting on (.*?): (\w+)")


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    found: list[tuple[str, re.Pattern[str]]] = []
    for predicate, template in ALL_TEMPLATES.items():
        regex = re.escape(template).replace(r"\{subject\}", r"(?P<subject>\S+)")
        regex = regex.replace(r"\{value\}", r"(?P<value>.+?)")
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
    def origins(self) -> list[str]:
        """Where each shown route starts ("via PTWC>hazard" -> PTWC)."""
        return [route.removeprefix("via ").split(">")[0] for route in self.via.split(" | ")]

    @property
    def rank(self) -> int:
        return max((rank(o) for o in self.origins), default=0) if self.via.startswith("via") else 0


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


def acted_on(context: str) -> set[str]:
    """The beliefs this desk's alerts rest on, except alerts held or reviewed since."""
    section = context.partition("## Your actions")[2].partition("\n\n")[0]
    found: set[str] = set()
    for line in section.splitlines()[1:]:
        m = ACTION.match(line)
        if m and m.group(5) == "done":
            found.update(m.group(4).split(", "))
    return found


def best(seen: list[Seen], predicate: str, subject: str | None = None) -> Seen | None:
    """The live figure from the most authoritative source; none from unknown accounts."""
    live = [
        b
        for b in seen
        if b.predicate == predicate
        and b.status == "active"
        and b.rank > 0
        and (subject is None or b.subject == subject)
    ]
    # equally authoritative figures that disagree: keep the first one, until a more
    # authoritative source settles it (a desk that flips between them reissues for nothing)
    return max(live, key=lambda b: (b.rank, -int(b.id[1:])), default=None)


Script = Generator[ToolCall, str, None]


def call(name: str, **arguments: Json) -> ToolCall:
    return ToolCall(name, dict(arguments), f"c-{name}")


# ---- the desks ----------------------------------------------------------------------------------


def hazard(context: str) -> Script:
    seen = beliefs(context)
    for predicate in (MAGNITUDE, DEPTH):
        figure = best(seen, predicate)
        if figure is not None:
            yield call("send", to="risk", belief_id=figure.id)  # a repeat is refused: harmless


def seismic(context: str) -> Script:
    """The day's seismic desk: a bulletin for every quake from the figures that count, redone
    only when one of them changes; the strongest quake's figures to risk."""
    seen = beliefs(context)
    for b in seen:
        if b.predicate == BULLETIN and b.status == "suspect":
            yield call("retract", belief_id=b.id, reason="a figure it rested on was revised")
    quakes = sorted({b.subject for b in seen if b.predicate == MAGNITUDE})
    strongest: tuple[float, Seen, Seen] | None = None
    for quake in quakes:
        magnitude, depth = best(seen, MAGNITUDE, quake), best(seen, DEPTH, quake)
        tsunami = best(seen, TSUNAMI, quake)
        if magnitude is None or depth is None or tsunami is None:
            continue
        if strongest is None or float(magnitude.value) > strongest[0]:
            strongest = (float(magnitude.value), magnitude, depth)
        text = bulletin_text(float(magnitude.value), float(depth.value), tsunami.value == "yes")
        live = [
            b
            for b in seen
            if b.predicate == BULLETIN and b.subject == quake and b.status == "active"
        ]
        if any(b.value == text for b in live):
            continue
        for old in live:
            yield call("retract", belief_id=old.id, reason="replaced")
        made = yield call(
            "assert_belief",
            subject=quake,
            predicate=BULLETIN,
            value=text,
            depends_on=[magnitude.id, depth.id, tsunami.id],
        )
        yield call("send", to="ops", belief_id=made.split()[-1])
    if strongest is not None:
        for figure in strongest[1:]:
            yield call("send", to="risk", belief_id=figure.id)  # a repeat is refused: harmless


def risk(context: str) -> Script:
    seen = beliefs(context)
    checked = {b.subject for b in seen if b.predicate == FAB_STATUS and b.via == "seen directly"}
    for claim in seen:
        if claim.predicate == FAB_STATUS and claim.via.startswith("via"):
            if claim.subject not in checked:
                yield call("fab_status", fab=claim.subject)
                checked.add(claim.subject)
    for b in seen:
        if b.predicate == EXPOSURE and b.status == "suspect":
            yield call("retract", belief_id=b.id, reason="a figure it rested on was revised")
    magnitude, depth = best(seen, MAGNITUDE), best(seen, DEPTH)
    if magnitude is None or depth is None:
        return
    rated = {b.subject for b in seen if b.predicate == EXPOSURE and b.status == "active"}
    for fab in FABS:
        if fab in rated:
            continue
        result = yield call(
            "exposure_rule",
            fab=fab,
            magnitude=float(magnitude.value),
            depth_km=float(depth.value),
        )
        level = result.split(" has ")[1].split()[0]
        made = yield call(
            "assert_belief",
            subject=fab,
            predicate=EXPOSURE,
            value=level,
            depends_on=[magnitude.id, depth.id],
        )
        yield call("send", to="ops", belief_id=made.split()[-1])


def ops(context: str) -> Script:
    done = acted_on(context)
    for b in beliefs(context):
        if b.status != "active" or b.id in done:
            continue
        if b.predicate == EXPOSURE:
            yield call("fab_alert", fab=b.subject, level=b.value, depends_on=[b.id])
        elif b.predicate == BULLETIN:
            yield call("bulletin_send", quake=b.subject, text=b.value, depends_on=[b.id])


def _nothing(context: str) -> Script:
    yield from ()


NODES: dict[str, Callable[[str], Script]] = {
    "hazard": hazard,
    "seismic": seismic,
    "risk": risk,
    "ops": ops,
}


def desk_team() -> ScriptedModel:
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

    return ScriptedModel(policy, model="hualien-stand-in")
