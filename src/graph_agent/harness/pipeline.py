"""Everything that happens between the simulator and the store, the same in every kind of run.

A scripted run (scripted.py) and a run with language-model agents (game.py) both feed the store
through this one class, so the knowledge graph is built identically whoever is acting.

  start(game)        create the agents, fields and the known map
  message(message)   an agent received a message: record it (and remember it, so it can be relayed)
  day(game, result)  a day was played: record the published evidence for every agent, reveal hidden
                     paths, and apply the adapter's evidence rule, calling Store.expose for each
                     agent that has just been proved wrong

Group correction (`warn_quorum`): an agent that catches a liar first-hand (the false claim came
straight from them, route [liar], so nobody else can be to blame) warns the neighbours it still
trusts. A warning travels one hop a day. A receiver ignores it if it has caught the sender or the
reporter lying (merely blaming an agent for passing on someone else's lie is not enough: it may be
honest); once `warn_quorum` independent reporters agree, it distrusts the liar too, which
propagates through its own graph exactly like a lie it had caught itself, and passes the warning
on. So the honest agents converge on who the liars are, without each having to be lied to.
"""

import heapq
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import TypedDict

from ..adapters import ringfire
from ..core.ids import Ids
from ..core.registry import Predicate
from ..core.store import Invalidation, Store
from ..sim.comms import Behaviour, Message
from ..sim.game import DayResult, Game


@dataclass
class Exposure:
    """One agent stopped trusting another, and what that changed in its beliefs."""

    viewer: str
    agent: str
    day: int
    reason: str
    changes: list[Invalidation] = field(default_factory=list[Invalidation])


@dataclass(frozen=True)
class Warning:
    """`sender` tells `receiver` that `accused` lies; `reporters` caught it first-hand."""

    sender: str
    receiver: str
    accused: str
    reporters: frozenset[str]
    day: int  # sent at the end of this day, delivered at the end of the next


class CardRules(TypedDict):
    """The rules an agent's role card states, read from the game (ringfire.role_card's settings)."""

    water: int | None
    cooldown: int
    regrow_days: int | None
    random_fires: bool
    horizon: int | None
    saboteurs: bool
    waste_penalty: float


def card_rules(game: Game) -> CardRules:
    """What every system tells its agents about the rules of this game."""
    rules, config = game.sim.rules, game.sim.world.config
    return {
        "water": rules.water_per_agent,
        "cooldown": rules.water_cooldown,
        "regrow_days": rules.regrow_days,
        "random_fires": config.random_ignition_chance > 0,
        "horizon": config.horizon,
        "saboteurs": Behaviour.SABOTEUR in game.net.imposters.values(),
        "waste_penalty": rules.waste_penalty,
    }


def role_card(agent: str, n_agents: int, fields: tuple[int, ...], rules: CardRules | None) -> str:
    """ringfire.role_card with the game's rules: the same text whichever system the agent uses."""
    if rules is None:
        return ringfire.role_card(agent, n_agents, fields)
    return ringfire.role_card(
        agent,
        n_agents,
        fields,
        water=rules["water"],
        cooldown=rules["cooldown"],
        regrow_days=rules["regrow_days"],
        random_fires=rules["random_fires"],
        horizon=rules["horizon"],
        saboteurs=rules["saboteurs"],
        waste_penalty=rules["waste_penalty"],
    )


def map_line(src: int, dst: int, weight: int, owner: int) -> str:
    """One known path on the map, as every system shows it."""
    return f"F{src} -> F{dst}: fire takes {weight} day(s) (A{owner} owns F{src})"


def hidden_map_line(src: int, dst: int, weight: int) -> str:
    """A hidden path, once fire has used it and everyone knows."""
    return f"F{src} -> F{dst}: a hidden path, now revealed; takes {weight} day(s)"


def outlook(
    edges: Iterable[tuple[int, int, int]],
    seen: Iterable[tuple[int, int]],
    own: Sequence[int],
    today: int,
) -> str:
    """When fire is next due at each of `own` fields, worked out from fires the agent has seen
    for itself (`seen`: (field, day) pairs of published evidence) along the paths it knows
    (`edges`: (src, dst, days)). Every system shows its agents this same section, built only from
    evidence, never from what anyone said, so it cannot be poisoned by a lie: what an agent can
    forecast depends on which fields it has been told to watch.
    """
    out: dict[int, list[tuple[int, int]]] = {}
    for src, dst, weight in edges:
        out.setdefault(src, []).append((dst, weight))

    def distances(source: int) -> dict[int, int]:
        dist = {source: 0}
        heap = [(0, source)]
        while heap:
            d, here = heapq.heappop(heap)
            if d > dist[here]:
                continue
            for dst, weight in out.get(here, []):
                if d + weight < dist.get(dst, d + weight + 1):
                    dist[dst] = d + weight
                    heapq.heappush(heap, (d + weight, dst))
        return dist

    fires = sorted(set(seen))
    reach = {source: distances(source) for source in {f for f, _ in fires}}
    lines: list[str] = []
    for target in own:
        # the earliest fire still to come: one that already passed says nothing about tomorrow
        due = [
            (day + reach[source][target], source, day)
            for source, day in fires
            if source != target and target in reach[source] and day + reach[source][target] >= today
        ]
        if not due:
            lines.append(f"F{target}: no fire you have seen is heading here")
            continue
        arrival, source, seen_day = min(due)
        lines.append(
            f"F{target}: fire due on day {arrival} unless stopped on the way "
            f"(F{source} seen burning on day {seen_day})"
        )
    return "## Fire outlook (from fires you have seen yourself)\n" + "\n".join(lines)


def episode(game: Game) -> int | None:
    """Days within which two arrivals at one field are the same fire: None if fields never regrow.

    A field that ignites on day d burns out on d + burn_days and regrows on d + burn_days +
    regrow_days, so the next fire there is at least one day after that.
    """
    regrow = game.sim.rules.regrow_days
    return None if regrow is None else game.sim.rules.burn_days + regrow


class Pipeline:
    def __init__(self, store: Store, ids: Ids | None = None, warn_quorum: int | None = None):
        self.store = store
        self.ids = ids or Ids()
        self.warn_quorum = warn_quorum  # None: agents never warn each other
        self.warnings: list[Warning] = []  # every warning sent, in order
        self._outbox: list[Warning] = []  # sent, not yet delivered
        self.reporters: dict[tuple[str, str], set[str]] = {}  # (viewer, accused) -> who caught it
        # claims heard straight from the agent that made them up: (receiver, maker, field, day)
        self._first_hand: list[tuple[int, int, int, int]] = []
        self._warned: set[tuple[str, str]] = set()  # (viewer, accused) it has warned others about
        # (viewer, agent): caught lying, first-hand or by warning. Only these silence a warning;
        # an agent merely blamed for passing on someone else's lie may well be honest.
        self.caught: set[tuple[str, str]] = set()
        self.exposures: list[Exposure] = []
        self.shown: set[tuple[int, int, int]] = set()  # (agent, field, day) evidence it was shown
        self._start_fires_published = False
        self.game: Game | None = None
        self.exposed: set[tuple[str, str]] = set()  # (viewer, agent) pairs already acted on
        self.predicates: dict[str, Predicate] = ringfire.PREDICATES

    def start(self, game: Game) -> None:
        self.game = game
        self.predicates = ringfire.predicates(episode(game))
        world = game.sim.world
        fields = [(f, world.owner(f)) for f in range(world.n_fields)]
        spread = [(e.src, e.dst, e.weight) for e in world.edges if not e.hidden]
        ringfire.setup_map(self.store, world.config.n_agents, fields, spread)

    def publish_start_fires(self, game: Game) -> None:
        """Tell everyone about the fires burning before day 0, so agents can act on day 0.

        Used by runs with live agents. The engine also reports these fires when it plays day 0,
        so `day` skips them for day 0 once they have been published here.
        """
        for field_number, _ in game.sim.world.initial_fires:
            for number in game.audience(field_number, 0):
                published = ringfire.EvidencePayload(day=0, field_id=field_number)
                ringfire.record_evidence(self.store, self.ids, published, number)
                self.shown.add((number, field_number, 0))
        self._start_fires_published = True

    def message(self, message: Message) -> None:
        viewer = ringfire.agent_id(message.receiver)
        if len(message.route) == 1:  # the sender made this claim itself
            self._first_hand.append(
                (message.receiver, message.sender, message.claim.field_id, message.claim.day)
            )
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
            distrusted={agent for v, agent in self.exposed if v == viewer},
        )
        if belief is None:
            return  # arrived through someone the receiver distrusts: seen, but believed by nobody
        self._tell_if_already_burnt(viewer, message.claim.field_id, message.claim.day, message.day)
        # A claim that contradicts evidence the receiver already holds is caught on arrival.
        for known in self.store.beliefs(viewer, subject=belief.subject, predicate=ringfire.ARRIVAL):
            if known.origin == "observed" and known.status in ("active", "suspect"):
                pairs = ringfire.agents_to_distrust(self.store, viewer, known, self.predicates)
                self._distrust(viewer, pairs, message.day)

    def _tell_if_already_burnt(
        self, viewer: str, field_number: int, claimed_day: int, today: int
    ) -> None:
        """Someone is told about a field that has already burnt: the engine shows them the truth
        at once, so a late claim can still be checked (only matters when evidence is private).
        For a field that burns again, only the fires the claim could be about are shown."""
        if self.game is None:
            return
        window = episode(self.game)
        number = int(viewer[1:])
        for ignited_on in self.game.sim.fields[field_number].ignitions:
            if window is not None and abs(ignited_on - claimed_day) > window:
                continue  # a different fire there
            if (number, field_number, ignited_on) in self.shown:
                continue  # already shown it
            # (Not "is it in the audience now": the audience counts this very message, so for a
            # fire published before the message, such as a start fire, that would always say yes
            # and the receiver would never see it, and would blame an honest sender.)
            self.shown.add((number, field_number, ignited_on))
            belief = ringfire.record_evidence(
                self.store,
                self.ids,
                ringfire.EvidencePayload(day=ignited_on, field_id=field_number),
                number,
            )
            pairs = ringfire.agents_to_distrust(self.store, viewer, belief, self.predicates)
            self._distrust(viewer, pairs, today)

    def day(self, game: Game, result: DayResult) -> None:
        day = result.report.day
        n_agents = game.sim.world.config.n_agents
        self._deliver_warnings(day)
        for edge in result.report.revealed_hidden:
            ringfire.reveal_hidden_edge(self.store, edge.src, edge.dst, edge.weight)
        for evidence in result.evidence:
            if day == 0 and self._start_fires_published and evidence.day == 0:
                if any(evidence.field_id == f for f, _ in game.sim.world.initial_fires):
                    continue  # already told to everyone before the day began
            published = ringfire.EvidencePayload(day=evidence.day, field_id=evidence.field_id)
            for number in evidence.audience:  # to everyone, or only those entitled to see it
                viewer = ringfire.agent_id(number)
                if (number, evidence.field_id, evidence.day) in self.shown:
                    continue
                self.shown.add((number, evidence.field_id, evidence.day))
                belief = ringfire.record_evidence(self.store, self.ids, published, number)
                pairs = ringfire.agents_to_distrust(self.store, viewer, belief, self.predicates)
                self._distrust(viewer, pairs, day)
        for number in range(n_agents):  # then catch claims whose day passed with no fire
            viewer = ringfire.agent_id(number)
            pairs = ringfire.agents_with_expired_claims(self.store, viewer, day)
            self._distrust(viewer, pairs, day)
        if self.warn_quorum is not None:
            self._warn_about_first_hand_liars(day)

    def _distrust(self, viewer: str, pairs: Sequence[ringfire.Blame], day: int) -> None:
        for agent, reason in pairs:
            if (viewer, agent) in self.exposed:
                continue
            self.exposed.add((viewer, agent))
            changes = self.store.expose(viewer, agent, tick=day, reason=reason)
            self.exposures.append(Exposure(viewer, agent, day, reason, changes))

    # ---- group correction ---------------------------------------------------------------------

    def _refuted(self, number: int, field_number: int, claimed: int, played: int) -> str | None:
        """Why what this agent has been shown proves the claim wrong, or None. It saw the fire on
        another day (within one fire's span), or the day has been played and it saw no fire,
        which it would have: being told about a field puts it in that field's audience."""
        seen = sorted(d for n, f, d in self.shown if n == number and f == field_number)
        if claimed in seen:
            return None
        window = episode(self.game) if self.game is not None else None
        for d in seen:
            if window is None or abs(d - claimed) <= window:
                return f"evidence says day {d}"
        return "no fire came that day" if claimed <= played else None

    def _warn_about_first_hand_liars(self, day: int) -> None:
        """Every claim heard straight from its maker that is now proved false: the maker lied,
        and nobody else can be to blame, so the receiver distrusts it (if it did not already)
        and warns the neighbours it trusts."""
        for number, maker, field_number, claimed in self._first_hand:
            viewer, accused = ringfire.agent_id(number), ringfire.agent_id(maker)
            if (viewer, accused) in self._warned:
                continue
            why = self._refuted(number, field_number, claimed, day)
            if why is None:
                continue
            self._warned.add((viewer, accused))
            self.caught.add((viewer, accused))
            reason = f"told F{field_number} on day {claimed}; {why}"
            self._distrust(viewer, [(accused, reason)], day)
            self.reporters.setdefault((viewer, accused), set()).add(viewer)
            self._warn_neighbours(viewer, accused, frozenset({viewer}), day, came_from=None)

    def _trusted_neighbours(self, viewer: str) -> list[str]:
        if self.game is None:
            return []
        number = int(viewer[1:])
        return [
            ringfire.agent_id(n)
            for n in self.game.net.neighbours(number)
            if (viewer, ringfire.agent_id(n)) not in self.caught
        ]

    def _warn_neighbours(
        self, viewer: str, accused: str, reporters: frozenset[str], day: int, came_from: str | None
    ) -> None:
        for neighbour in self._trusted_neighbours(viewer):
            if neighbour in (accused, came_from):
                continue
            warning = Warning(viewer, neighbour, accused, reporters, day)
            self.warnings.append(warning)
            self._outbox.append(warning)

    def _deliver_warnings(self, day: int) -> None:
        """Deliver the warnings sent on earlier days (one hop a day)."""
        due = [w for w in self._outbox if w.day < day]
        self._outbox = [w for w in self._outbox if w.day >= day]
        for warning in due:
            self._receive_warning(warning, day)

    def _receive_warning(self, warning: Warning, day: int) -> None:
        viewer, accused = warning.receiver, warning.accused
        if self.game is not None and int(viewer[1:]) in self.game.net.imposters:
            return  # a liar does not pass warnings on
        if (viewer, warning.sender) in self.caught:
            return  # from someone it has caught lying
        trusted = {r for r in warning.reporters if (viewer, r) not in self.caught}
        known = self.reporters.setdefault((viewer, accused), set())
        known |= trusted
        if (viewer, accused) in self._warned or self.warn_quorum is None:
            return  # it has passed this on already
        if len(known) < self.warn_quorum:
            return
        self._warned.add((viewer, accused))
        self.caught.add((viewer, accused))
        self._distrust(viewer, [(accused, "warned by " + ", ".join(sorted(known)))], day)
        self._warn_neighbours(viewer, accused, frozenset(known), day, came_from=warning.sender)
