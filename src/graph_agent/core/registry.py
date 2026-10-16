"""Predicates and the contradiction rule.

An adapter declares every predicate it uses, as a dict of name -> Predicate. That dict decides
whether two beliefs conflict, so the core needs no knowledge of what a predicate means.
"""

from collections.abc import Mapping

from pydantic import BaseModel

from .model import Belief


class Predicate(BaseModel):
    name: str
    single_valued: bool = True  # a subject has at most one value at a time
    tolerance: float = 0.0  # numeric values closer than this do not conflict
    # numeric values further apart than this describe separate events (a field that burns again
    # weeks later), so they do not conflict either; None = any two different values conflict
    separate_beyond: float | None = None


_LIVE = ("active", "suspect")


def _overlap(a: Belief, b: Belief) -> bool:
    """Do the two validity ranges share at least one tick? None means open-ended."""
    starts_before_other_ends = (
        b.valid_to is None or a.valid_from is None or a.valid_from <= b.valid_to
    )
    other_starts_before_end = (
        a.valid_to is None or b.valid_from is None or b.valid_from <= a.valid_to
    )
    return starts_before_other_ends and other_starts_before_end


def _differ(a: Belief, b: Belief, predicate: Predicate) -> bool:
    numbers = (int, float)
    if isinstance(a.value, numbers) and isinstance(b.value, numbers):
        if not isinstance(a.value, bool) and not isinstance(b.value, bool):
            gap = abs(a.value - b.value)
            separate = predicate.separate_beyond is not None and gap > predicate.separate_beyond
            return gap > predicate.tolerance and not separate
    return a.value != b.value


def contradicts(a: Belief, b: Belief, predicates: Mapping[str, Predicate]) -> bool:
    """Same subject and predicate, single-valued, live, overlapping validity, values differ (by
    more than the tolerance, and not so far apart that they are separate events)."""
    if a.id == b.id or a.subject != b.subject or a.predicate != b.predicate:
        return False
    if a.status not in _LIVE or b.status not in _LIVE:
        return False
    predicate = predicates[a.predicate]  # KeyError if the adapter never registered it
    if not predicate.single_valued or not _overlap(a, b):
        return False
    return _differ(a, b, predicate)
