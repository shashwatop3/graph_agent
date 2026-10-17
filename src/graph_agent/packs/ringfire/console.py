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
from .sim.scenario import ClaimSpec, RulesSpec, Scenario, SendSpec
from .standin import honest_agent

# fire arrives at 1, grows or falls by 1 a day up to 5, a field 2 days at 5 is lost; water is free
LINEAR_RULES: RulesSpec = {
    "dynamics": "linear",
    "step": 1.0,
    "max_intensity": 5.0,
    "lost_after": 2,
    "water_per_agent": None,
    "water_cooldown": 0,
    "relight": True,  # a new fire starts when every fire is out
}


LINEAR_START = 3.0
LINEAR_DAYS = 30
LINEAR_REGROW = 2  # days a lost field takes to grow back
LINEAR_RANDOM_FIRES = 0.15  # chance each day that a new fire starts somewhere


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
        if options.get("liars"):
            _choose_liars(scenario, [int(a) for a in str(options["liars"]).split(",")], knobs)
        if options.get("fire", "linear") == "linear":
            rules: RulesSpec = {**LINEAR_RULES}
            regrow = options.get("regrow", LINEAR_REGROW)
            rules["regrow_days"] = None if regrow in (None, "none", 0) else int(regrow)
            if "cap" in options:
                rules["max_intensity"] = float(options["cap"])
            if "lost_after" in options:
                rules["lost_after"] = int(options["lost_after"])
            if options.get("water") is not None:
                rules["water_per_agent"] = int(options["water"])
            if options.get("arrive") in ("step", "source"):
                rules["arrive"] = options["arrive"]
            scenario["rules"] = {**scenario.get("rules", {}), **rules}
            # the first fire starts strong enough to spread before its owner can put it out
            scenario["world"] = {
                **scenario["world"],
                "initial_intensity": float(options.get("start", LINEAR_START)),
                # fire put out can come round the ring again, so the game has a fixed length
                "horizon": int(options.get("days", LINEAR_DAYS)),
                "random_ignition_chance": float(options.get("random_fires", LINEAR_RANDOM_FIRES)),
            }
        team = team_for(
            scenario,
            quorum=None if quorum is None else int(quorum),
            wake=bool(options.get("wake", False)),
            rerouter=bool(options.get("rerouter", False)),
            blame=options.get("blame", "first_hop"),
            repair=bool(options.get("repair", True)),
            trace_provenance=bool(options.get("trace_provenance", True)),
        )
        if options.get("keep_lying", False):
            team.settings.extra["keep_lying"] = True  # false alarms all game: see Imposters
        return team

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


def _choose_liars(scenario: Scenario, liars: list[int], knobs: Knobs) -> None:
    """Make exactly these agents the imposters, with the scenario's usual opening lie: fire "will
    reach" a field on the far side of the ring, earlier than it could, told to each neighbour."""
    n = scenario["world"].get("n_agents", 8)
    scenario["imposters"] = [{"agent": a, "behaviour": knobs.behaviour} for a in liars]
    if knobs.behaviour != "false_alarm":
        scenario["sends"] = []
        return
    n_fields = n * scenario["world"].get("fields_per_agent", 1)
    sends: list[SendSpec] = []
    for liar in liars:
        for neighbour in ((liar - 1) % n, (liar + 1) % n):
            if neighbour not in liars:
                claim: ClaimSpec = {"field_id": n_fields // 2, "day": max(1, n_fields // 4)}
                sends.append({"day": 1, "sender": liar, "receiver": neighbour, "claim": claim})
    scenario["sends"] = sends
