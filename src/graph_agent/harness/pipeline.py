"""Everything that happens between the simulator and the store, the same in every kind of run.

A scripted run (scripted.py) and a run with language-model agents (game.py) both feed the store
through this one class, so the knowledge graph is built identically whoever is acting.

  start(game)        create the agents, fields and the known map
  message(message)   an agent received a message: record it (and remember it, so it can be relayed)
  day(game, result)  a day was played: record the published evidence for every agent, reveal hidden
                     paths, and apply the adapter's evidence rule, calling Store.expose for each
                     agent that has just been proved wrong
"""

from dataclasses import dataclass, field

from ..adapters import ringfire
from ..core.ids import Ids
from ..core.store import Invalidation, Store


@dataclass
class Exposure:
    """One agent stopped trusting another, and what that changed in its beliefs."""

    viewer: str
    agent: str
    day: int
    reason: str
    changes: list[Invalidation] = field(default_factory=list)


class Pipeline:
    def __init__(self, store: Store, ids: Ids | None = None):
        self.store = store
        self.ids = ids or Ids()
        self.exposures: list[Exposure] = []
        self._start_fires_published = False
        self._exposed: set[tuple[str, str]] = set()  # (viewer, agent) pairs already acted on
        # the latest message each agent received about a given claim, so it can be relayed
        self.received: dict[tuple[str, int, int], object] = {}

    def start(self, game) -> None:
        world = game.sim.world
        fields = [(f, world.owner(f)) for f in range(world.n_fields)]
        spread = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]
        ringfire.setup_map(self.store, world.config.n_agents, fields, spread)

    def publish_start_fires(self, game) -> None:
        """Tell everyone about the fires burning before day 0, so agents can act on day 0.

        Used by runs with live agents. The engine also reports these fires when it plays day 0,
        so `day` skips them for day 0 once they have been published here.
        """
        for field_number, _ in game.sim.world.initial_fires:
            for number in range(game.sim.world.config.n_agents):
                published = {"day": 0, "field_id": field_number}
                ringfire.record_evidence(self.store, self.ids, published, number)
        self._start_fires_published = True

    def message(self, message) -> None:
        viewer = ringfire.agent_id(message.receiver)
        belief = ringfire.record_message(
            self.store,
            self.ids,
            {
                "sender": message.sender,
                "receiver": message.receiver,
                "route": list(message.route),
                "day": message.day,
                "claim": {"field_id": message.claim.field_id, "day": message.claim.day},
            },
            distrusted={agent for v, agent in self._exposed if v == viewer},
        )
        if belief is None:
            return  # arrived through someone the receiver distrusts: seen, but believed by nobody
        self.received[(viewer, message.claim.field_id, message.claim.day)] = message
        # A claim that contradicts evidence the receiver already holds is caught on arrival.
        for known in self.store.beliefs(viewer, subject=belief.subject, predicate=ringfire.ARRIVAL):
            if known.origin == "observed" and known.status in ("active", "suspect"):
                pairs = ringfire.agents_to_distrust(self.store, viewer, known)
                self._distrust(viewer, pairs, message.day)

    def day(self, game, result) -> None:
        day = result.report.day
        n_agents = game.sim.world.config.n_agents
        for edge in result.report.revealed_hidden:
            ringfire.reveal_hidden_edge(self.store, edge.src, edge.dst, edge.weight)
        for evidence in result.evidence:
            if day == 0 and self._start_fires_published and evidence.day == 0:
                if any(evidence.field_id == f for f, _ in game.sim.world.initial_fires):
                    continue  # already told to everyone before the day began
            published = {"day": evidence.day, "field_id": evidence.field_id}
            for number in range(n_agents):  # evidence goes to everyone
                viewer = ringfire.agent_id(number)
                belief = ringfire.record_evidence(self.store, self.ids, published, number)
                pairs = ringfire.agents_to_distrust(self.store, viewer, belief)
                self._distrust(viewer, pairs, day)
        for number in range(n_agents):  # then catch claims whose day passed with no fire
            viewer = ringfire.agent_id(number)
            pairs = ringfire.agents_with_expired_claims(self.store, viewer, day)
            self._distrust(viewer, pairs, day)

    def _distrust(self, viewer: str, pairs, day: int) -> None:
        for agent, reason in pairs:
            if (viewer, agent) in self._exposed:
                continue
            self._exposed.add((viewer, agent))
            changes = self.store.expose(viewer, agent, tick=day, reason=reason)
            self.exposures.append(Exposure(viewer, agent, day, reason, changes))
