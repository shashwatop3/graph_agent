"""The life pack in the console: its teams, tools, run options, world and recorded runs."""

import json
from pathlib import Path
from typing import Any, cast

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
from graph_agent.frame.nodes import approvals
from graph_agent.frame.spec import TeamSpec
from graph_agent.harness.llm import ModelClient

from .pack import FACTS, PLANS
from .real import build_real, real_team
from .run import build_life, score_life
from .standin import life_team
from .teams import TEAMS
from .tools import LifeTools
from .world import LifeWorld, minutes, tick_label

RUNS = Path(__file__).resolve().parents[4] / "runs"  # the repository's runs/ folder


class LifeConsole:
    name = "life"
    title = "Life: mail, calendar, travel, promises, money"
    cache_suffix = "-life"
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
        RunOption(
            "extraction",
            "Reading mail",
            [Choice("gold", "Structured (connector)"), Choice("model", "A model reads it")],
        ),
    ]

    def templates(self) -> list[Template]:
        found = [Template(n, make().name, make().description) for n, make in TEAMS.items()]
        real = real_team()
        return [*found, Template("real", real.name, real.description)]

    def team(self, name: str, options: dict[str, Any]) -> TeamSpec:
        if name == "real":
            return real_team()
        team = TEAMS[name]()
        team.settings.extra["case"] = name  # which checks of the week it answers for
        return team

    def catalogue(self) -> PackCatalogue:
        tools = [
            {
                "name": t.name,
                "description": t.description,
                "outward": t.outward,
                "checking": t.observes is not None,
            }
            for t in LifeTools(LifeWorld()).list_tools()
        ]
        return PackCatalogue(tools=tools, predicates={**FACTS, **PLANS})

    def stand_in(self, team: TeamSpec) -> ModelClient:
        return life_team()

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
        if team.settings.extra.get("real"):
            return self.start_real(team, client, store, log)
        runtime, world, _ = build_life(
            team, client, store, extraction=options.get("extraction", "gold"), log=log
        )

        def score() -> dict[str, Any]:
            run = score_life(str(team.settings.extra.get("case", "")), runtime, world, runtime.pack)  # type: ignore[arg-type]
            return {**run.score, "checks": run.checks}

        return Session(runtime, lambda: world_view(world), score, tick_label)

    def start_real(
        self, team: TeamSpec, client: ModelClient, store: Store, log: EventLog
    ) -> Session:
        """Your real accounts, through the MCP servers (see real.py)."""
        runtime, pack, _ = build_real(team, client, store, log)

        def world() -> dict[str, Any]:
            seen = [e for e in runtime.log.events if e.kind == "item"]
            return {
                "lens": "real",
                "items": [
                    {
                        "id": e.data["item"],
                        "tick": e.tick,
                        "kind": e.data.get("item_kind"),
                        "from": e.data["source"],
                        "subject": str(
                            cast(dict[str, Any], e.data.get("payload") or {}).get("subject", "")
                        ),
                    }
                    for e in seen[-40:]
                ],
            }

        def score() -> dict[str, Any]:
            book = approvals(runtime).proposals.values()
            return {
                "items": sum(1 for e in runtime.log.events if e.kind == "item"),
                "claims_read": sum(len(c) for c in pack.extracted.values()),
                "actions_proposed": len(book),
                "actions_held": sum(p.status in ("held", "reviewed") for p in book),
                "exposures": len(runtime.exposures),
                "tokens_in": sum(t.tokens_in for _, _, t in runtime.turns) + pack.extract_tokens[0],
            }

        return Session(runtime, world, score, pack.clock_label)

    def recorded(self) -> list[Recorded]:
        found: list[Recorded] = []
        for path in sorted(RUNS.glob("life*/*.events.jsonl")):
            meta = path.parent / "meta.json"
            if not meta.exists() or json.loads(meta.read_text()).get("replayable", 0) < 2:
                continue  # an older run: a replay would ask the model again
            case, _, extraction = path.name.removesuffix(".events.jsonl").partition("-")
            last = json.loads((path.read_text().splitlines()[-1:] or ["{}"])[0])
            found.append(
                Recorded(
                    str(path.relative_to(RUNS.parent)),
                    case,
                    {"extraction": extraction, "model": "claude-haiku-5-5"},
                    last.get("checks_passed"),
                    last.get("checks_total"),
                )
            )
        return found


def world_view(w: LifeWorld) -> dict[str, Any]:
    return {
        "lens": "life",
        "events": [vars(e) for e in w.events.values()],
        "cabs": [vars(c) for c in w.cabs.values()],
        "tasks": [vars(t) for t in w.tasks.values()],
        "subscriptions": dict(w.sub_cards),
        "payments": [vars(p) for p in w.payments],
        "sent": [vars(s) for s in w.sent],
        "mail": [
            {
                "id": m.id,
                "tick": m.tick,
                "from": m.sender,
                "to": m.to,
                "subject": m.subject,
                "feed": m.feed,
                "scam": m.scam,
            }
            for m in w.inbox
        ],
        "departs": w.departure(),
        "now": minutes("Mon 00:00") + w.now(),
    }


LIFE = LifeConsole()
