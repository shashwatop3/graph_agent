"""The Hualien adapter: a second domain on the same, unchanged core.

The story is real. On 2 April 2024 an earthquake struck near Hualien City, Taiwan (USGS event
us7000m9g4). Early reports, as the tsunami warning centres issued them, gave magnitude 7.5 at a
depth of 11 km. USGS's reviewed solution is magnitude 7.4 at 40 km. A supply-chain risk desk that
had already rated a nearby fab as "high exposure" from the early figure has to be told that the
figure changed, and which of its conclusions rested on it.

Nothing here is about fire or a ring. The same six node types and nine relationships carry it:

  Agent        an agency or a desk ("PTWC", "WireService", "HazardDesk", "RiskDesk")
  Entity       the earthquake and the fabs that might be hit
  Observation  a report, with the agencies it was relayed through (RELAYED_VIA, in order)
  Belief       "magnitude of Q1 is 7.5", "exposure of FabA is high"
  Correction   a retraction of a superseded figure, or an exposure of an unreliable relay

What differs from Ring Fire is only what an adapter supplies: the predicates, the parser for a
report, the rule for when a belief is superseded (here: a more authoritative source disagrees),
the derived computation (how exposed is a fab), the render templates and the role card.

It imports only the core and takes plain dicts, like the Ring Fire adapter.
"""

from typing import NotRequired, TypedDict

from ..core.ids import Ids
from ..core.model import Agent, Belief, Edge, Entity, Observation
from ..core.registry import Predicate
from ..core.store import Store

# ---- predicates ---------------------------------------------------------------------------------

MAGNITUDE = "quake.magnitude"
DEPTH = "quake.depth_km"
EXPOSURE = "fab.exposure"

PREDICATES = {
    # a quake has one magnitude; solutions within 0.05 of each other are the same figure
    MAGNITUDE: Predicate(name=MAGNITUDE, single_valued=True, tolerance=0.05),
    # depth estimates scatter, so 5 km of difference is not a disagreement
    DEPTH: Predicate(name=DEPTH, single_valued=True, tolerance=5),
    EXPOSURE: Predicate(name=EXPOSURE, single_valued=True),
}

TEMPLATES = {
    MAGNITUDE: "{subject} has magnitude {value}",
    DEPTH: "{subject} was {value} km deep",
    EXPOSURE: "{subject} has {value} exposure",
}

# How far to trust a source's figures when two sources disagree: higher wins. A relay (a wire
# service, a desk) has no authority of its own: it carries a figure, it does not originate one.
AUTHORITY = {"USGS": 3, "PTWC": 2, "ATWC": 2}


# ---- the map ------------------------------------------------------------------------------------


def setup(store: Store, agents: list[str], quake: str, fabs: dict[str, float]) -> None:
    """Create the agencies and desks, the earthquake, and the fabs (name -> km from epicentre)."""
    for agent in agents:
        store.add_node(Agent(id=agent))
    store.add_node(Entity(id=quake, type="Quake"))
    for fab, distance in fabs.items():
        store.add_node(Entity(id=fab, type="Fab", props={"distance_km": distance}))


# ---- parser -------------------------------------------------------------------------------------


class Report(TypedDict):
    """A report as the adapter reads it. `route` starts at the source and ends at the receiver's
    sender; magnitude and depth_km may each be missing."""

    route: list[str]
    receiver: str
    tick: int
    quake: str
    magnitude: NotRequired[float]
    depth_km: NotRequired[float]


def _live(belief: Belief) -> bool:
    return belief.status in ("active", "suspect")


def _believe(
    store: Store,
    ids: Ids,
    viewer: str,
    subject: str,
    predicate: str,
    value: float,
    tick: int,
    obs_id: str,
) -> Belief:
    """Find or create the receiver's belief, and attach the observation as support."""
    belief = next(
        (
            b
            for b in store.beliefs(viewer, subject=subject, predicate=predicate)
            if _live(b) and b.value == value and b.origin == "told"
        ),
        None,
    )
    if belief is None:
        belief = Belief(
            id=ids.next("B"),
            owner=viewer,
            subject=subject,
            predicate=predicate,
            value=value,
            origin="told",
            kind="fact",
            created_tick=tick,
            updated_tick=tick,
        )
        store.add_node(belief)
        store.add_edge(Edge(kind="ABOUT", src=belief.id, dst=subject, props={"role": "subject"}))
    store.add_edge(Edge(kind="SUPPORTS", src=obs_id, dst=belief.id, props={"tick": tick}))
    return belief


def record_report(store: Store, ids: Ids, report: Report) -> list[Belief]:
    """A report reached a desk: an observation with the route it took, and what it claims.

    report: {"route": ["PTWC", "WireService"], "receiver": "RiskDesk", "tick": 1,
             "quake": "Q1", "magnitude": 7.5, "depth_km": 11}
    The route lists the agencies it passed through; the first is the source. Any of magnitude
    and depth_km may be missing.
    """
    viewer, route = report["receiver"], report["route"]
    observation = Observation(
        id=ids.next("O"),
        kind="message",
        payload=dict(report),
        received_by=viewer,
        sender=route[-1],
        about_tick=report["tick"],
        received_tick=report["tick"],
    )
    store.add_node(observation)
    for hop, agency in enumerate(route):
        store.add_edge(Edge(kind="RELAYED_VIA", src=observation.id, dst=agency, props={"hop": hop}))
    store.add_edge(
        Edge(kind="ABOUT", src=observation.id, dst=report["quake"], props={"role": "mentioned"})
    )
    made: list[Belief] = []
    for predicate, value in ((MAGNITUDE, report.get("magnitude")), (DEPTH, report.get("depth_km"))):
        if value is not None:
            made.append(
                _believe(
                    store,
                    ids,
                    viewer,
                    report["quake"],
                    predicate,
                    value,
                    report["tick"],
                    observation.id,
                )
            )
    return made


# ---- the supersession rule (this domain's "evidence rule") -------------------------------------


def _sources(store: Store, viewer: str, belief: Belief) -> set[str]:
    """Who originated this belief: the first agency on each route that supports it."""
    return {route[0] for route in store.support_routes(viewer, belief.id) if route}


def _authority(sources: set[str]) -> int:
    return max((AUTHORITY.get(source, 0) for source in sources), default=0)


def retract_superseded(store: Store, viewer: str, new: Belief, tick: int) -> list[str]:
    """`new` just arrived. Retract live beliefs it contradicts that came only from less
    authoritative sources, and return their ids.

    A belief from a source of equal or higher authority is left alone: two equally authoritative
    figures that disagree are a conflict for the desk to resolve, not something to settle by rule.
    Each retraction marks everything that was derived from the old figure as suspect.
    """
    newer = _authority(_sources(store, viewer, new))
    retracted: list[str] = []
    for old in store.conflicts(viewer, new.id, PREDICATES):
        if old.origin == "told" and _authority(_sources(store, viewer, old)) < newer:
            store.retract(
                viewer, old.id, tick, "superseded by a figure from a more authoritative source"
            )
            retracted.append(old.id)
    return retracted


# ---- derived computation ------------------------------------------------------------------------


def assess_exposure(store: Store, ids: Ids, viewer: str, fab: str, tick: int) -> Belief | None:
    """How exposed is `fab`, given the magnitude and depth the desk currently believes?

    A deliberately simple rule of thumb, enough to make the point: effective strength falls with
    distance and rises when the quake is shallow. The result is a derived belief that points back
    (DERIVED_FROM) at the magnitude and depth beliefs it used, so correcting either flags it.
    Returns None if the desk does not yet hold both figures.
    """
    entity = store.get(viewer, fab)
    quake = next(iter(store.beliefs(viewer, predicate=MAGNITUDE)), None)
    if not isinstance(entity, Entity) or quake is None:
        return None
    figures: dict[str, Belief] = {}
    for predicate in (MAGNITUDE, DEPTH):
        live = [
            b for b in store.beliefs(viewer, subject=quake.subject, predicate=predicate) if _live(b)
        ]
        if not live:
            return None
        # if several live figures disagree, use the one from the most authoritative source
        figures[predicate] = max(live, key=lambda b: _authority(_sources(store, viewer, b)))
    magnitude, depth = figures[MAGNITUDE].value, figures[DEPTH].value
    effective = round(magnitude - entity.props["distance_km"] / 100 + max(0, 30 - depth) / 100, 2)
    level = "high" if effective >= 6.4 else "medium" if effective >= 5.5 else "low"

    belief = Belief(
        id=ids.next("B"),
        owner=viewer,
        subject=fab,
        predicate=EXPOSURE,
        value=level,
        origin="derived",
        kind="assessment",
        created_tick=tick,
        updated_tick=tick,
    )
    store.add_node(belief)
    store.add_edge(Edge(kind="ABOUT", src=belief.id, dst=fab, props={"role": "subject"}))
    for source in figures.values():
        store.add_edge(
            Edge(
                kind="DERIVED_FROM",
                src=belief.id,
                dst=source.id,
                props={"via": "exposure_rule", "tick": tick},
            )
        )
    return belief


# ---- role card ----------------------------------------------------------------------------------


def role_card(desk: str) -> str:
    return (
        f"You are the {desk} at a company with fabs near a seismic zone. Reports about an "
        f"earthquake reach you through agencies and wire services; each shows the route it took. "
        f"Early figures are often revised. Rate each fab's exposure from the magnitude, depth and "
        f"distance you currently believe, and when a more authoritative source revises a figure, "
        f"redo every assessment that used the old one."
    )
