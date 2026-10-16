"""Plays a scripted scenario end to end with no LLM: simulator -> adapter -> store.

The scenario scripts what every agent sends. Everything else is the real pipeline:
  * each message the engine delivers is recorded as an observation and a told belief,
  * each day's published evidence is recorded for every agent,
  * the adapter's evidence rule decides whom each agent stops trusting,
  * `Store.expose` propagates that, and we record exactly what it changed.

This is the harness's job because it is the only package allowed to import both the simulator and
the adapter. It converts the simulator's objects into the plain dicts the adapter understands.
"""

from dataclasses import dataclass, field

from ..adapters import ringfire
from ..core.store import Invalidation, Store
from ..sim.scenario import run_scenario


@dataclass
class Exposure:
    """One agent stopped trusting another, and what that changed in its beliefs."""

    viewer: str
    agent: str
    day: int
    reason: str
    changes: list[Invalidation] = field(default_factory=list)


def play_scripted(scenario: dict, store: Store):
    """Run `scenario` into `store`. Returns (exposures in order, the finished Game)."""
    ids = ringfire.Ids()
    exposures: list[Exposure] = []
    exposed: set[tuple[str, str]] = set()  # (viewer, agent) pairs already acted on

    def distrust(viewer: str, pairs, day: int) -> None:
        for agent, reason in pairs:
            if (viewer, agent) in exposed:
                continue
            exposed.add((viewer, agent))
            changes = store.expose(viewer, agent, tick=day, reason=reason)
            exposures.append(Exposure(viewer, agent, day, reason, changes))

    def on_start(game) -> None:
        world = game.sim.world
        fields = [(f, world.owner(f)) for f in range(world.n_fields)]
        spread = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]
        ringfire.setup_map(store, world.config.n_agents, fields, spread)

    def on_send(game, message) -> None:
        ringfire.record_message(
            store,
            ids,
            {
                "sender": message.sender,
                "receiver": message.receiver,
                "route": list(message.route),
                "day": message.day,
                "claim": {"field_id": message.claim.field_id, "day": message.claim.day},
            },
        )

    def on_day(game, result) -> None:
        day = result.report.day
        n_agents = game.sim.world.config.n_agents
        for edge in result.report.revealed_hidden:
            ringfire.reveal_hidden_edge(store, edge.src, edge.dst, edge.weight)
        for evidence in result.evidence:
            published = {"day": evidence.day, "field_id": evidence.field_id}
            for number in range(n_agents):  # evidence goes to everyone
                viewer = ringfire.agent_id(number)
                belief = ringfire.record_evidence(store, ids, published, number)
                distrust(viewer, ringfire.agents_to_distrust(store, viewer, belief), day)
        for number in range(n_agents):  # then catch claims whose day passed with no fire
            viewer = ringfire.agent_id(number)
            distrust(viewer, ringfire.agents_with_expired_claims(store, viewer, day), day)

    game = run_scenario(scenario, on_start=on_start, on_send=on_send, on_day=on_day)
    return exposures, game
