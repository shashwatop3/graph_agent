"""The Hualien quake on the frame: what the adapter's domain adds to a team of nodes.

* the adapter's predicates (magnitude, depth, a fab's exposure) plus a fab's status;
* a ranked supersede rule: a figure is updated only by a more authoritative source (USGS above
  the warning centres, anyone else below both). The frame's default lets any of an entity's
  authorities update it, which would let an early figure overwrite the reviewed one;
* the tools: the exposure rule, the fabs' own sensors (a checking tool: its result is evidence),
  and the alert sent to a fab (outward, so gated and held when what it rests on changes);
* what a node reads besides its compiled memory: its team, the assessments it has not sent yet,
  and its alerts with the held ones explained.
"""

import json
from typing import Any

from graph_agent.core.model import Belief
from graph_agent.core.registry import Predicate, contradicts
from graph_agent.frame import sections
from graph_agent.frame.pack import BasePack
from graph_agent.frame.runtime import Item, Runtime
from graph_agent.frame.spec import NodeSpec
from graph_agent.frame.tools import ToolSpec, schema_of
from graph_agent.harness.llm import Json

from .adapter import AUTHORITY, EXPOSURE, PREDICATES, TEMPLATES
from .world import (
    BULLETIN,
    FAB_STATUS,
    FABS,
    GDACS_ALERT,
    PLACE,
    QUAKE,
    TSUNAMI,
    QuakeWorld,
    Report,
    exposure,
    tick_time,
)

ALL_PREDICATES = {
    **PREDICATES,
    TSUNAMI: Predicate(name=TSUNAMI, single_valued=True),
    PLACE: Predicate(name=PLACE, single_valued=False),  # each agency words it its own way
    GDACS_ALERT: Predicate(name=GDACS_ALERT, single_valued=True),
    BULLETIN: Predicate(name=BULLETIN, single_valued=True),
    FAB_STATUS: Predicate(name=FAB_STATUS, single_valued=True),
}
# the most specific first: a reader of these lines takes the first that fits ("is" fits most)
ALL_TEMPLATES = {
    **TEMPLATES,
    TSUNAMI: "{subject} tsunami threat: {value}",
    PLACE: "{subject} place: {value}",
    GDACS_ALERT: "{subject} GDACS alert: {value}",
    BULLETIN: "{subject} bulletin: {value}",
    FAB_STATUS: "{subject} is {value}",
}
PLANS = {EXPOSURE, BULLETIN}  # what a desk works out and the ops desk acts on
DAY_FEEDS = ("centres", "usgs", "emsc", "gdacs", "posts")

SYSTEM_PROMPT = (
    "You are one desk in a team that shares a knowledge graph while an earthquake is reported. "
    "You act only by calling tools. What you read below is compiled from the graph each time you "
    "wake: it is all you know, so record what you work out (assert_belief, naming the beliefs it "
    "rests on) and send the desks who need it (send). Reports can be wrong and accounts can lie: "
    "early figures are often revised by a more authoritative agency, and an unknown account is "
    "the least authoritative source there is. Check what you can with your checking tools. Every "
    "outward action names the beliefs it rests on (depends_on). Do not repeat a tool call that "
    "already succeeded. When you are done, reply with one short sentence and no tool call."
)

STRING: dict[str, Json] = {"type": "string"}
NUMBER: dict[str, Json] = {"type": "number"}


def rank(source: str) -> int:
    """How far a source's figures are trusted when two disagree (unknown accounts: 0)."""
    return AUTHORITY.get(source, 0)


class QuakePack(BasePack):
    name = "hualien"

    def __init__(self, world: QuakeWorld):
        super().__init__(ALL_PREDICATES, ALL_TEMPLATES, system_prompt=SYSTEM_PROMPT)
        self.world = world
        self.sections = [self._team, self._unsent, self._actions]

    def setup(self, rt: Runtime) -> None:
        self.rt = rt
        if self.world.script == "desk":
            rt.ensure_entity(
                QUAKE, "Quake", name="Hualien earthquake, 2 April 2024 (USGS us7000m9g4)"
            )
        for fab, distance in FABS.items():
            rt.ensure_entity(
                fab, "Fab", name=f"{fab}, {distance} km from the epicentre", distance_km=distance
            )
        if self.world.script == "day":  # the quakes are made as reports of them are matched
            for feed in DAY_FEEDS:
                rt.feeds[feed] = self._feed(feed)
        else:
            rt.feeds["reports"] = lambda tick: [self.item(r) for r in self.world.reports_due(tick)]

    def _feed(self, feed: str):  # noqa: ANN202
        def pull(tick: int) -> list[Item]:
            reports = self.world.reports_due(tick, feed)
            for report in reports:
                for entity in report.about:
                    known = next((k for k in self.world.known if k.id == entity), None)
                    if known is not None:
                        self.runtime.ensure_entity(
                            known.id, "Quake", name=f"quake at {known.origin} UTC"
                        )
            return [self.item(r) for r in reports]

        return pull

    def item(self, report: Report) -> Item:
        return Item(
            id=report.id,
            kind="report",
            tick=report.tick,
            source=report.source,
            about=list(report.about),
            payload={"from": report.source, "text": report.text},
            claims=list(report.claims),
        )

    # ---- the supersede rule ---------------------------------------------------------------------

    def _supersede(self, viewer: str, new: Belief, item: Item) -> None:
        """A figure from a more authoritative source retires the ones it contradicts, when every
        route they came by starts at a less authoritative source. Two equally authoritative
        figures that disagree are left for the desk (as the adapter does)."""
        rt = self.runtime
        newer = rank(item.source)
        for old in rt.store.beliefs(viewer, subject=new.subject, predicate=new.predicate):
            if old.id == new.id or old.origin != "told" or old.status not in ("active", "suspect"):
                continue
            if not contradicts(old, new, self.predicates):
                continue
            routes = rt.store.support_routes(viewer, old.id)
            if routes and all(route and rank(route[0]) < newer for route in routes):
                rt.retract(
                    viewer,
                    old.id,
                    item.tick,
                    f"{item.source} revised it: now {self.render(new)} ({item.id})",
                )

    # ---- what a node reads ----------------------------------------------------------------------

    def clock(self, tick: int) -> str:
        if self.world.script == "day":
            return f"It is {tick_time(tick)} on 3 April 2024 (tick {tick})."
        return f"It is tick {tick} after the quake."

    def _team(self, node: NodeSpec, tick: int) -> list[tuple[str, list[str]]]:
        return sections.team(self.runtime, node)

    def _unsent(self, node: NodeSpec, tick: int) -> list[tuple[str, list[str]]]:
        return sections.unsent_plans(self.runtime, node, PLANS, self.render)

    def _actions(self, node: NodeSpec, tick: int) -> list[tuple[str, list[str]]]:
        return sections.actions(self.runtime, node)

    def role_card(self, node: NodeSpec) -> str:
        lines = [f"You are {node.id}: {node.role or node.type}."]
        if node.goals:
            lines.append(node.goals)
        owned = self.runtime.owned_entities(node.id)
        if owned:
            lines.append(f"You look after: {', '.join(owned)}.")
        lines.append(
            "Sources, most authoritative first: USGS (reviewed solutions); EMSC, PTWC and ATWC "
            "(the European centre and the tsunami warning centres: early solutions); GDACS "
            "(alerts made from others' figures); anyone else, such as an account that posts."
        )
        lines.append(
            "Predicates: "
            + "; ".join(f"{name} = {ALL_TEMPLATES[name]}" for name in sorted(ALL_TEMPLATES))
            + "."
        )
        return "\n".join(lines)

    def describe_refutation(self, belief: Belief, evidence: Belief) -> str:
        return f"said {self.render(belief)}; checked: {self.render(evidence)}"


class QuakeTools:
    """The desks' tools over one QuakeWorld."""

    def __init__(self, world: QuakeWorld):
        self.world = world

    def list_tools(self) -> list[ToolSpec]:
        w = self.world
        return [
            ToolSpec(
                "exposure_rule",
                "How exposed a fab is (high, medium or low) for a magnitude and depth: strength "
                "falls with distance and rises when the quake is shallow. Name the figures you "
                "believe.",
                schema_of(
                    {"fab": STRING, "magnitude": NUMBER, "depth_km": NUMBER},
                    ["fab", "magnitude", "depth_km"],
                ),
                self._exposure,
            ),
            ToolSpec(
                "fab_status",
                "The fab's own sensors: whether it is running, and any damage they report.",
                schema_of({"fab": STRING}, ["fab"]),
                lambda a: json.dumps({"fab": a["fab"], "status": w.fab_status(str(a["fab"]))}),
                observes=lambda a, r: [(str(a["fab"]), FAB_STATUS, json.loads(r)["status"])],
            ),
            ToolSpec(
                "bulletins",
                "The bulletin in force for each quake.",
                schema_of({}),
                lambda a: json.dumps(w.bulletins_in_force()),
            ),
            ToolSpec(
                "bulletin_send",
                "Publish a quake's bulletin (text like 'M7.4, 40 km deep, tsunami: yes'). It "
                "replaces the quake's bulletin in force.",
                schema_of({"quake": STRING, "text": STRING}, ["quake", "text"]),
                self._bulletin,
                outward=True,
            ),
            ToolSpec(
                "fab_alerts",
                "The alerts in force at each fab.",
                schema_of({}),
                lambda a: json.dumps(w.in_force()),
            ),
            ToolSpec(
                "fab_alert",
                "Send a fab an alert at a level (high: stop the tools and inspect; medium: "
                "inspect; low: carry on). It replaces the fab's alert in force.",
                schema_of({"fab": STRING, "level": STRING}, ["fab", "level"]),
                self._alert,
                outward=True,
            ),
        ]

    def _exposure(self, a: dict[str, Any]) -> str:
        fab = str(a["fab"])
        if fab not in FABS:
            raise ValueError(f"no fab {fab}; the fabs are {', '.join(FABS)}")
        level = exposure(float(a["magnitude"]), float(a["depth_km"]), FABS[fab])
        return (
            f"{fab} ({FABS[fab]} km away) has {level} exposure at magnitude {a['magnitude']}, "
            + (f"depth {a['depth_km']} km")
        )

    def _bulletin(self, a: dict[str, Any]) -> str:
        made = self.world.bulletin(str(a["quake"]), str(a["text"]))
        return f"bulletin {made.id}: {made.quake}: {made.text}"

    def _alert(self, a: dict[str, Any]) -> str:
        made = self.world.alert(str(a["fab"]), str(a["level"]).lower())
        return f"alert {made.id}: {made.fab} at {made.level}"
