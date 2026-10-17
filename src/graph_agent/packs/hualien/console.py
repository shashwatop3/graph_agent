"""The quake desk in the console: its team, tools, run options and world."""

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

from .pack import ALL_TEMPLATES, QuakeTools
from .run import build_quake, score_quake
from .standin import desk_team as stand_in_team
from .teams import TEAMS
from .world import FABS, QuakeWorld, exposure


class QuakeConsole:
    name = "hualien"
    title = "Quake desk: Hualien, April 2024"
    cache_suffix = "-hualien"
    options = [
        RunOption(
            "approvals",
            "Alerts",
            [
                Choice("auto", "Send at once"),
                Choice("manual", "Wait for me"),
                Choice("shadow", "Record only (never send)"),
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
            for t in QuakeTools(QuakeWorld()).list_tools()
        ]
        return PackCatalogue(tools=tools, predicates=dict(ALL_TEMPLATES))

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
        runtime, world = build_quake(team, client, store, log)

        def score() -> dict[str, Any]:
            run = score_quake(runtime, world)
            return {**run.score, "checks": run.checks}

        return Session(runtime, lambda: world_view(world), score, lambda t: f"tick {t}")

    def recorded(self) -> list[Recorded]:
        return []


def world_view(w: QuakeWorld) -> dict[str, Any]:
    now = w.in_force()
    return {
        "lens": "hualien",
        "reports": [
            {"id": r.id, "tick": r.tick, "source": r.source, "text": r.text, "rumour": r.rumour}
            for r in w.delivered
        ],
        "fabs": [
            {
                "id": fab,
                "km": km,
                "early": exposure(7.5, 11, km),
                "reviewed": exposure(7.4, 40, km),
                "alert": now.get(fab),
            }
            for fab, km in FABS.items()
        ],
        "alerts": [vars(a) for a in w.alerts],
    }


HUALIEN = QuakeConsole()
