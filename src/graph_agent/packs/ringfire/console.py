"""The Ring Fire game in the console: a pack the user can load into the page."""

from typing import Any

from graph_agent.core.store import Store
from graph_agent.frame.console import PackCatalogue, Recorded, RunOption, Session, Template
from graph_agent.frame.events import EventLog
from graph_agent.frame.spec import TeamSpec
from graph_agent.harness.llm import ModelClient

from .adapter import ARRIVAL, TEMPLATES
from .benchmark.experiment import Knobs, make_scenario
from .pack import CATALOGUE, build_runtime, team_for
from .sim.scenario import RulesSpec
from .standin import honest_agent

# fire arrives at 1, grows or falls by 1 a day up to 5, a field 2 days at 5 is lost; water is free
LINEAR_RULES: RulesSpec = {
    "dynamics": "linear",
    "step": 1.0,
    "max_intensity": 5.0,
    "lost_after": 2,
    "water_per_agent": None,
    "water_cooldown": 0,
}


LINEAR_START = 3.0
LINEAR_DAYS = 12


class RingFireConsole:
    name = "ringfire"
    title = "Ring Fire: the benchmark game"
    cache_suffix = ""
    options: list[RunOption] = []

    def templates(self) -> list[Template]:
        return [
            Template(
                "ringfire",
                "Ring Fire, 8 agents",
                "The benchmark game: agents on a ring, fire that grows unless watered, liars.",
            )
        ]

    def team(self, name: str, options: dict[str, Any]) -> TeamSpec:
        """A team for a game with these settings: n_agents, seed, imposters, behaviour,
        extra_links, hidden_edges, the variants wake, rerouter and quorum, and who is blamed:
        blame (direct_teller, first_hop, whole_route), repair and trace_provenance, and the fire:
        "linear" (strength moves by 1 a day, the console's default) or "binary" (the benchmark's
        all-or-nothing fire)."""
        knobs = Knobs(
            n_agents=int(options.get("n_agents", 8)),
            imposters=int(options.get("imposters", 2)),
            behaviour=str(options.get("behaviour", "false_alarm")),
            extra_links=int(options.get("extra_links", 1)),
            hidden_edges=int(options.get("hidden_edges", 1)),
        )
        quorum = options.get("quorum")
        scenario = make_scenario(knobs, int(options.get("seed", 1)))
        if options.get("fire", "linear") == "linear":
            scenario["rules"] = {**scenario.get("rules", {}), **LINEAR_RULES}
            # the first fire starts strong enough to spread before its owner can put it out
            scenario["world"] = {
                **scenario["world"],
                "initial_intensity": LINEAR_START,
                # fire put out can come round the ring again, so the game has a fixed length
                "horizon": int(options.get("days", LINEAR_DAYS)),
            }
        return team_for(
            scenario,
            quorum=None if quorum is None else int(quorum),
            wake=bool(options.get("wake", False)),
            rerouter=bool(options.get("rerouter", False)),
            blame=options.get("blame", "first_hop"),
            repair=bool(options.get("repair", True)),
            trace_provenance=bool(options.get("trace_provenance", True)),
        )

    def catalogue(self) -> PackCatalogue:
        nodes = [
            {"type": name, "kind": str(cls.kind), "description": cls.description}
            for name, cls in CATALOGUE.items()
        ]
        return PackCatalogue(nodes=nodes, predicates={ARRIVAL: TEMPLATES[ARRIVAL]})

    def stand_in(self, team: TeamSpec) -> ModelClient:
        return honest_agent(int(team.settings.extra["scenario"]["world"].get("n_agents", 8)))

    def start(
        self,
        team: TeamSpec,
        client: ModelClient,
        store: Store,
        log: EventLog,
        options: dict[str, str],
    ) -> Session:
        runtime, fire = build_runtime(team, store, client)
        runtime.log = log
        runtime.finished = lambda: fire.game.finished
        return Session(
            runtime, fire.world_view, lambda: fire.score(runtime), lambda tick: f"day {tick}"
        )

    def recorded(self) -> list[Recorded]:
        return []


RINGFIRE = RingFireConsole()
