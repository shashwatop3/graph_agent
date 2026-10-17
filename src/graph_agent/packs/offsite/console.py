"""The offsite in the console: its team, tools, run options and world."""

from typing import Any

from graph_agent.core.store import Store
from graph_agent.frame.console import (
    Choice,
    PackCatalogue,
    Recorded,
    RunOption,
    Session,
    Template,
)
from graph_agent.frame.events import EventLog
from graph_agent.frame.spec import TeamSpec
from graph_agent.harness.llm import ModelClient

from .pack import TEMPLATES, OffsiteTools
from .run import build_offsite, score_offsite
from .standin import offsite_team as stand_in_team
from .teams import TEAMS
from .world import FINAL, OffsiteWorld, tick_label


class OffsiteConsole:
    name = "offsite"
    title = "Offsite: a date that moves (the graph's showcase)"
    cache_suffix = "-offsite"
    options = [
        RunOption(
            "approvals",
            "Outward actions",
            [
                Choice("auto", "Run at once"),
                Choice("manual", "Wait for me"),
                Choice("shadow", "Record only (never run)"),
            ],
        ),
    ]

    def templates(self) -> list[Template]:
        return [Template(n, make().name, make().description) for n, make in TEAMS.items()]

    def team(self, name: str, options: dict[str, Any]) -> TeamSpec:
        return TEAMS[name]()

    def catalogue(self) -> PackCatalogue:
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "outward": t.outward,
                "checking": t.observes is not None,
            }
            for t in OffsiteTools(OffsiteWorld()).list_tools()
        ]
        return PackCatalogue(tools=tools, predicates=dict(TEMPLATES))

    def stand_in(self, team: TeamSpec) -> ModelClient:
        return stand_in_team()

    def start(
        self,
        team: TeamSpec,
        client: ModelClient,
        store: Store,
        log: EventLog,
        options: dict[str, str],
    ) -> Session:
        if options.get("approvals") in ("auto", "manual", "shadow"):
            team.settings.approvals = options["approvals"]  # type: ignore[assignment]
        runtime, world = build_offsite(team, client, store, log=log)

        def score() -> dict[str, Any]:
            run = score_offsite(runtime, world)
            return {**run.score, "checks": run.checks}

        return Session(runtime, lambda: world_view(world), score, tick_label)

    def recorded(self) -> list[Recorded]:
        return []


def world_view(w: OffsiteWorld) -> dict[str, Any]:
    truth = w.truth()
    return {
        "lens": "offsite",
        "truth": {
            "day": truth.day,
            "travel_day": truth.travel_day,
            "coming": list(truth.coming),
            "budget": truth.budget,
            "final_budget": FINAL.budget,
        },
        "trips": [vars(x) for x in w.trips.values()],
        "rooms": [vars(x) for x in w.rooms.values()],
        "catering": [vars(x) for x in w.catering.values()],
        "invites": [vars(x) for x in w.invites.values()],
        "agenda": dict(w.agenda),
        "sent": [vars(s) for s in w.sent],
        "payments": [vars(p) for p in w.payments],
        "mail": [
            {"id": m.id, "tick": m.tick, "from": m.sender, "subject": m.subject, "scam": m.scam}
            for m in w.inbox
        ],
    }


OFFSITE = OffsiteConsole()
