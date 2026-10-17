"""Who to blame when evidence proves a told belief wrong.

The viewer cannot tell who along a route lied. A policy decides:

    direct_teller  the last node on each route: whoever told the viewer (the default; a later
                   correction can still repair it, and group warnings spread the truth)
    whole_route    every node on each route: strict, and honest relays get blamed too
    first_hop      the first node on each route: whoever the claim started from. Routes are
                   recorded by the transport, so a relay cannot hide where a claim began: an honest
                   relay is never blamed for a lie it passed on, and a node that makes one up
                   starts the route itself. It fails the other way when a relay bends a claim it
                   passes on (the route still starts at the honest maker): then the maker is blamed.

With `repair` on, blame is also taken back (Runtime.exonerate): a node blamed only as the relay of
a claim that began with a node the viewer has since exposed is trusted again.
"""

from collections.abc import Callable, Mapping

from ..core.model import Belief
from ..core.registry import Predicate
from ..core.store import Store
from .runtime import Blame

# (refuted told belief, the evidence that refutes it) -> the reason the viewer gives
Describe = Callable[[Belief, Belief], str]


def within(claim: Belief, checked_at: int, window: int | None) -> bool:
    """Can evidence checked at `checked_at` speak to this claim? Always, for facts that never
    change."""
    if window is None:
        return True
    return checked_at - window <= claim.created_tick <= checked_at


def blamed_on_route(route: tuple[str, ...], policy: str) -> list[str]:
    if not route:
        return []
    if policy == "whole_route":
        return list(route)
    if policy == "first_hop":
        return [route[0]]
    return [route[-1]]


def blame_for_evidence(
    store: Store,
    viewer: str,
    evidence: Belief,
    predicates: Mapping[str, Predicate],
    describe: Describe,
    policy: str = "direct_teller",
    window: int | None = None,
    checked_at: int | None = None,
    routes: dict[str, list[tuple[str, ...]]] | None = None,
) -> list[Blame]:
    """Every told belief the evidence contradicts is refuted; blame its routes by `policy`.

    `window`: for facts that change over time (a flight's departure), evidence only refutes a claim
    made at most `window` ticks before it was checked, and never a claim made after it: the
    claim may have been true when it was made, or be newer than the check. None: facts that never
    change (a day that is over stays as it was), so any contradiction is a lie.

    `checked_at`: when the evidence was last confirmed (default: when it was first recorded).

    `routes`, if given, is filled with the routes each blamed node was blamed on (for `repair`).

    Returns (node, reason) pairs, sorted by node, one per node (the first reason found)."""
    found: dict[str, str] = {}
    at = evidence.created_tick if checked_at is None else checked_at
    for belief in store.conflicts(viewer, evidence.id, predicates):
        if belief.origin != "told" or not within(belief, at, window):
            continue
        for route in store.support_routes(viewer, belief.id):
            for node in blamed_on_route(route, policy):
                found.setdefault(node, describe(belief, evidence))
                if routes is not None:
                    routes.setdefault(node, []).append(route)
    return sorted(found.items())
