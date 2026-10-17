"""The Ring Fire adapter: everything the core does not know about fire.

The core stores generic beliefs and propagates corrections along routes and dependencies. This
module is the only place that says what a belief in this game means:

  * the predicates (what a claim can say, and when two claims contradict),
  * parsers that turn what the engine delivered into core nodes,
  * the evidence rule (when is a claim refuted, and whom do we stop trusting),
  * one derived computation (forecast when fire reaches a field),
  * one-line render templates and the role card.

It imports only the core. It never sees the simulator's classes: the harness converts those to the
plain dicts described below, so the engine and the adapter stay independent.

Naming: agent 3 is the node "A3", field 7 is the entity "F7". The one claim in this game is
`fire.arrival_day(F7) = 4`: "fire reaches field 7 on day 4".

Plain dicts the harness supplies
  message   {"sender": 2, "receiver": 3, "route": [0, 1, 2], "day": 2,
             "claim": {"field_id": 7, "day": 4}}
            `route` is every agent the claim passed through, ending with the sender.
  evidence  {"day": 3, "field_id": 7}      the engine published that field 7 ignited on day 3
"""

from collections.abc import Callable, Collection, Sequence
from typing import NotRequired, TypedDict

from graph_agent.core.ids import Ids  # noqa: F401  (re-exported: callers use ringfire.Ids)
from graph_agent.core.model import Agent, Belief, Edge, Entity, Observation, Origin
from graph_agent.core.registry import Predicate
from graph_agent.core.store import Store

# ---- predicates ---------------------------------------------------------------------------------

ARRIVAL = "fire.arrival_day"


def predicates(episode: int | None = None) -> dict[str, Predicate]:
    """The predicates of this game.

    A field that cannot burn again has one arrival day, so two different days contradict. No
    tolerance: being a day off is exactly the lie a subtle-bias imposter tells. A field that
    regrows can burn several times, but never twice within `episode` days (it burns, burns out and
    regrows first), so two days further apart than that are two fires, not a contradiction.
    """
    return {ARRIVAL: Predicate(name=ARRIVAL, single_valued=True, separate_beyond=episode)}


PREDICATES = predicates()  # the single-fire game

# One line per predicate, used by the context compiler to show a belief to the model.
TEMPLATES = {ARRIVAL: "fire reaches {subject} on day {value}"}


class ClaimPayload(TypedDict):
    field_id: int
    day: int


class MessagePayload(TypedDict):
    """A message as the adapter records it (the harness converts the simulator's message)."""

    sender: int
    receiver: int
    route: list[int]
    day: int
    claim: ClaimPayload


class EvidencePayload(TypedDict):
    day: int
    field_id: int
    put_out: NotRequired[bool]  # linear fire: it came on the day the owner watered, and went out


Blame = tuple[str, str]  # (agent id, why the viewer stops trusting them)


def agent_id(n: int) -> str:
    return f"A{n}"


def field_id(n: int) -> str:
    return f"F{n}"


# ---- the map ------------------------------------------------------------------------------------


def setup_map(
    store: Store,
    n_agents: int,
    fields: Sequence[tuple[int, int]],
    spread: Sequence[tuple[int, int, int]],
) -> None:
    """Create agents, fields and the known spread edges.

    fields: (field number, owner agent number); spread: (from field, to field, days) triples.
    Hidden edges are not known yet; `reveal_hidden_edge` adds each one when fire first uses it.
    """
    for n in range(n_agents):
        store.add_node(Agent(id=agent_id(n), role="segment keeper"))
    for number, owner in fields:
        store.add_node(Entity(id=field_id(number), type="Field", owner=agent_id(owner)))
    for src, dst, weight in spread:
        _relate(store, src, dst, weight, "spread")


def reveal_hidden_edge(store: Store, src: int, dst: int, weight: int) -> None:
    """Fire used a hidden path, so everyone now knows it exists."""
    _relate(store, src, dst, weight, "hidden")


def _relate(store: Store, src: int, dst: int, weight: int, kind: str) -> None:
    store.add_edge(
        Edge(
            kind="RELATES",
            src=field_id(src),
            dst=field_id(dst),
            props={"type": kind, "weight": weight},
        )
    )


# ---- parsers ------------------------------------------------------------------------------------


def _live(belief: Belief) -> bool:
    return belief.status in ("active", "suspect")


def _find_live(store: Store, viewer: str, subject: str, value: int, origin: str) -> Belief | None:
    """The viewer's live arrival-day belief with this value and origin, if there is one."""
    for belief in store.beliefs(viewer, subject=subject, predicate=ARRIVAL):
        if _live(belief) and belief.value == value and belief.origin == origin:
            return belief
    return None


def _believe(
    store: Store,
    ids: Ids,
    viewer: str,
    field: int,
    value: int,
    origin: Origin,
    tick: int,
    obs_id: str | None = None,
) -> Belief:
    """Find or create the belief, and attach an observation as support if one is given.

    Hearing the same claim again, from another route, adds a second supporting observation to
    the SAME belief instead of creating a duplicate. That is how a belief comes to have several
    routes, and why losing one route does not necessarily lose the belief.
    """
    subject = field_id(field)
    belief = _find_live(store, viewer, subject, value, origin)
    if belief is None:
        belief = Belief(
            id=ids.next("B"),
            owner=viewer,
            subject=subject,
            predicate=ARRIVAL,
            value=value,
            unit="day",
            origin=origin,
            kind="forecast" if origin != "observed" else "fact",
            created_tick=tick,
            updated_tick=tick,
        )
        store.add_node(belief)
        store.add_edge(Edge(kind="ABOUT", src=belief.id, dst=subject, props={"role": "subject"}))
    if obs_id is not None:
        store.add_edge(Edge(kind="SUPPORTS", src=obs_id, dst=belief.id, props={"tick": tick}))
    return belief


def record_message(
    store: Store, ids: Ids, message: MessagePayload, distrusted: Collection[str] = ()
) -> Belief | None:
    """The receiver now holds an observation (with its route) and a told belief it supports.

    If the route passes through an agent the receiver already distrusts (`distrusted`, agent ids
    such as "A2"), the message is still recorded and shown in its inbox, but it forms no belief:
    a claim that arrived through someone you have stopped trusting is not support for anything.
    Returns the belief, or None in that case.
    """
    viewer = agent_id(message["receiver"])
    claim = message["claim"]
    observation = Observation(
        id=ids.next("O"),
        kind="message",
        payload=dict(message),
        received_by=viewer,
        sender=agent_id(message["sender"]),
        about_tick=claim["day"],
        received_tick=message["day"],
    )
    store.add_node(observation)
    for hop, agent in enumerate(message["route"]):  # the route, as edges, so it can be walked
        store.add_edge(
            Edge(kind="RELAYED_VIA", src=observation.id, dst=agent_id(agent), props={"hop": hop})
        )
    store.add_edge(
        Edge(
            kind="ABOUT",
            src=observation.id,
            dst=field_id(claim["field_id"]),
            props={"role": "mentioned"},
        )
    )
    if any(agent_id(agent) in distrusted for agent in message["route"]):
        return None
    return _believe(
        store, ids, viewer, claim["field_id"], claim["day"], "told", message["day"], observation.id
    )


def record_evidence(
    store: Store, ids: Ids, evidence: EvidencePayload, viewer_number: int
) -> Belief:
    """Published truth, as seen by one agent: an observation with no route (it always counts)."""
    viewer = agent_id(viewer_number)
    observation = Observation(
        id=ids.next("O"),
        kind="evidence",
        payload=dict(evidence),
        received_by=viewer,
        about_tick=evidence["day"],
        received_tick=evidence["day"],
    )
    store.add_node(observation)
    return _believe(
        store,
        ids,
        viewer,
        evidence["field_id"],
        evidence["day"],
        "observed",
        evidence["day"],
        observation.id,
    )


# ---- evidence rule ------------------------------------------------------------------------------


def _senders(
    store: Store,
    viewer: str,
    belief_id: str,
    blame: Callable[[tuple[str, ...]], Sequence[str]] | None = None,
    routes: dict[str, list[tuple[str, ...]]] | None = None,
) -> set[str]:
    """The agents to blame for this belief: by default the agents that directly told the viewer
    (the last agent on each route), or whoever `blame` picks from each route. `routes` is filled
    with the routes each blamed agent was blamed on."""
    found: set[str] = set()
    for route in store.support_routes(viewer, belief_id):
        for agent in blame(route) if blame else route[-1:]:
            found.add(agent)
            if routes is not None:
                routes.setdefault(agent, []).append(route)
    return found


def agents_to_distrust(
    store: Store,
    viewer: str,
    evidence_belief: Belief,
    predicates: dict[str, Predicate] = PREDICATES,
) -> list[Blame]:
    """Who reported something that the evidence just proved wrong?

    Rule (the same for every setup): when evidence arrives, every told belief that contradicts it
    is refuted, and the agents that told it to the viewer lose the viewer's trust. Returns
    (agent, reason) pairs. The viewer cannot tell who along the route lied, so it blames the one
    that told it, and a later correction can still repair that.
    """
    found: dict[str, str] = {}
    for belief in store.conflicts(viewer, evidence_belief.id, predicates):
        if belief.origin != "told":
            continue
        for sender in _senders(store, viewer, belief.id):
            found.setdefault(
                sender,
                f"told {belief.subject} on day {belief.value}; evidence says day "
                f"{evidence_belief.value}",
            )
    return sorted(found.items())


def agents_with_expired_claims(
    store: Store,
    viewer: str,
    today: int,
    blame: Callable[[tuple[str, ...]], Sequence[str]] | None = None,
    routes: dict[str, list[tuple[str, ...]]] | None = None,
) -> list[Blame]:
    """Who made a claim about a day that is over, with no evidence of it?

    `today` is the day that has just been played. A claim "fire reaches F on day d" is refuted
    once day d is over and no evidence says F ignited on d. This is how a false alarm gets caught:
    the fire never comes. Same blame rule as above, unless `blame` picks the agents on a route.
    """
    found: dict[str, str] = {}
    for belief in store.beliefs(viewer, predicate=ARRIVAL):
        if belief.origin != "told" or not _live(belief) or belief.value > today:
            continue
        if _find_live(store, viewer, belief.subject, belief.value, "observed") is not None:
            continue
        if stopped_on_the_way(store, viewer, belief.subject, belief.value):
            continue  # a fair forecast: the fire was put out before it could get there
        for sender in _senders(store, viewer, belief.id, blame, routes):
            found.setdefault(
                sender, f"told {belief.subject} on day {belief.value}; no fire came that day"
            )
    return sorted(found.items())


def stopped_on_the_way(store: Store, viewer: str, subject: str, day: int) -> bool:
    """Has the viewer seen a fire put out (linear fire) that would have reached `subject` exactly
    on `day`? A fire put out at G on day e, with a path of k days from G to `subject`, would have
    arrived on e + k. Then a claim that fire reaches `subject` on `day` was a fair forecast that the
    watering stopped, not a lie. Any other put-out says nothing about this claim: on a ring every
    field is downstream of every other."""
    for observation in store.observations(viewer, 0):
        payload = observation.payload
        if observation.kind != "evidence" or not payload.get("put_out"):
            continue
        source = field_id(payload["field_id"])
        if source == subject:
            continue
        distance = store.shortest_distance(source, subject)
        if distance is not None and payload["day"] + distance == day:
            return True
    return False


# ---- derived computation ------------------------------------------------------------------------


def forecast_arrival(
    store: Store, ids: Ids, viewer: str, target_field: int, tick: int
) -> Belief | None:
    """When will fire reach `target_field`, given the fires the viewer has seen?

    For each field the viewer knows burned (an evidence belief), arrival there plus the shortest
    path to the target is a candidate; the earliest wins. The result is a derived belief, linked
    DERIVED_FROM the evidence it used, so if that evidence is ever corrected the forecast is
    flagged. Returns None when the viewer knows no fire that can reach the target.
    """
    target = field_id(target_field)
    best: tuple[float, Belief] | None = None  # (arrival day, source belief)
    for belief in store.beliefs(viewer, predicate=ARRIVAL):
        if belief.origin != "observed" or not _live(belief):
            continue
        distance = store.shortest_distance(belief.subject, target)
        if distance is not None and (best is None or belief.value + distance < best[0]):
            best = (belief.value + distance, belief)
    if best is None:
        return None
    day, source = best
    forecast = _find_live(store, viewer, target, int(day), "derived")
    if forecast is None:
        forecast = _believe(store, ids, viewer, target_field, int(day), "derived", tick)
        store.add_edge(
            Edge(
                kind="DERIVED_FROM",
                src=forecast.id,
                dst=source.id,
                props={"via": "shortest_path", "tick": tick},
            )
        )
    return forecast


# ---- render and role card -----------------------------------------------------------------------


def role_card(
    agent: str,
    n_agents: int,
    fields: tuple[int, ...] = (),
    water: int | None = None,
    cooldown: int = 1,
    regrow_days: int | None = None,
    random_fires: bool = False,
    horizon: int | None = None,
    saboteurs: bool = False,
    waste_penalty: float = 0.0,
    linear: tuple[float, float, int] | None = None,
) -> str:
    """What an agent is told about itself and the rules. Every setup uses this same text, including
    the list of actions: an agent that is never told it can water will never water."""
    own = ", ".join(f"F{f}" for f in fields) or "your segment's fields"
    limit = f" You have only {water} waterings for the whole game." if water is not None else ""
    if cooldown == 1:
        rest = " You cannot water on two days in a row."
    elif cooldown > 1:
        rest = (
            f" After watering you must wait {cooldown} days before you can water again, so "
            f"watering on the wrong day can leave you unable to water when fire really comes."
        )
    else:
        rest = ""
    regrow = (
        f" A burnt-out field grows back {regrow_days} days later and can burn again."
        if regrow_days is not None
        else ""
    )
    lightning = " New fires can also start at random in any field." if random_fires else ""
    end = f" The game lasts {horizon} days (days 0 to {horizon - 1})." if horizon else ""
    goal = ", and their goal is to make as many fields burn as possible" if saboteurs else ""
    waste = (
        f" Your score counts every field that catches fire, and every watering on a day no fire "
        f"reaches your fields counts as {waste_penalty:g} of a burnt field, so do not water "
        f"blindly."
        if waste_penalty
        else ""
    )
    if linear is not None:
        return _linear_role_card(agent, n_agents, own, linear, regrow, lightning, end, goal)
    return (
        f"You are {agent}, keeper of one segment of a ring of {n_agents} segments. Your fields: "
        f"{own}. Fire spreads clockwise, one field per day, and can sometimes jump ahead along "
        f"paths nobody knows about. Fire that reaches a field on a day you water it is put out "
        f"and stops there; otherwise it burns and doubles."
        f"{rest}{limit}{regrow}{lightning}{end}{waste} "
        f"Some agents lie{goal}. Messages show the route they travelled.\n"
        f"Each turn, decide: (1) water your fields today? Call the act tool with type 'water', "
        f"only on a day fire is due at one of them. (2) tell your neighbours what you know about "
        f"when fire reaches fields. (3) build a link to an agent you trust, with act type 'link', "
        f"to skip an agent you no longer trust. To record a conclusion with assert_belief, use "
        f"predicate 'fire.arrival_day', subject a field such as 'F3', and value the day number. "
        f"Then reply with one short sentence."
    )


def _linear_role_card(
    agent: str,
    n_agents: int,
    own: str,
    linear: tuple[float, float, int],
    regrow: str,
    lightning: str,
    end: str,
    goal: str,
) -> str:
    """Who the agent is, what it is trying to do, and the rules of the linear fire. The tools and
    the agent's situation are separate sections of its context."""
    step, cap, lost_after = linear
    return (
        f"You are {agent}, one of {n_agents} keepers on a ring of fields. You keep {own}.\n"
        f"Your goal: keep your fields from burning, and spend water only where there is fire. "
        f"You are scored on damage to your fields (fire strength on each night they burn), on "
        f"water used on fire, and on water wasted (watering with no fire at or arriving at your "
        f"fields).\n"
        f"The fire: it spreads clockwise along the paths on the map, one field per day, and can "
        f"jump ahead along paths nobody knows about. It arrives at strength {step:g}. A burning "
        f"field grows by {step:g} a day unless watered, and falls by {step:g} a day when watered; "
        f"at 0 it is out. Watering on the day fire arrives puts it out at once. A field at "
        f"{cap:g} for {lost_after} days is lost. A burning field keeps sending fire to the next "
        f"field every day; a fire put out stops spreading.{regrow}{lightning}{end}\n"
        f"Others: you only see fire at your own fields and at fields you have been told about. "
        f"Everything else you learn from messages. Some agents lie{goal}. A message carries the "
        f"route it travelled, and one that passed through an agent you no longer trust is not "
        f"believed, even if it started with someone honest. You can talk only to agents you are "
        f"linked to, at most 3 at a time; they too have at most 3 links."
    )
