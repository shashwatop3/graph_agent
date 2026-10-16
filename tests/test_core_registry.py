import pytest

from graph_agent.core.model import Belief
from graph_agent.core.registry import Predicate, contradicts

REGISTRY = {
    "level": Predicate(name="level", single_valued=True, tolerance=0.5),
    "tag": Predicate(name="tag", single_valued=False),
}


def b(bid, value, predicate="level", subject="E1", **kw) -> Belief:
    return Belief(id=bid, owner="A1", subject=subject, predicate=predicate, value=value, **kw)


def test_different_values_of_a_single_valued_predicate_contradict():
    assert contradicts(b("1", 10), b("2", 20), REGISTRY)


def test_values_within_tolerance_do_not_contradict():
    assert not contradicts(b("1", 10), b("2", 10.4), REGISTRY)
    assert contradicts(b("1", 10), b("2", 10.6), REGISTRY)


def test_non_numeric_values_must_match_exactly():
    assert contradicts(b("1", "red"), b("2", "blue"), REGISTRY)
    assert not contradicts(b("1", "red"), b("2", "red"), REGISTRY)


def test_booleans_are_not_treated_as_numbers_for_tolerance():
    assert contradicts(b("1", True), b("2", False), REGISTRY)


def test_multi_valued_predicates_never_contradict():
    assert not contradicts(b("1", "a", "tag"), b("2", "b", "tag"), REGISTRY)


def test_different_subject_or_predicate_never_contradicts():
    assert not contradicts(b("1", 1), b("2", 9, subject="E2"), REGISTRY)
    assert not contradicts(b("1", 1), b("2", 9, predicate="tag"), REGISTRY)


def test_a_belief_does_not_contradict_itself():
    assert not contradicts(b("1", 1), b("1", 9), REGISTRY)


def test_non_overlapping_validity_does_not_contradict():
    early = b("1", 1, valid_from=0, valid_to=4)
    late = b("2", 9, valid_from=5, valid_to=9)
    assert not contradicts(early, late, REGISTRY)
    assert contradicts(early, b("3", 9, valid_from=4, valid_to=9), REGISTRY)  # share tick 4


def test_open_ended_validity_overlaps_everything_after_its_start():
    assert contradicts(b("1", 1, valid_from=3), b("2", 9, valid_from=10, valid_to=12), REGISTRY)
    assert not contradicts(b("1", 1, valid_to=3), b("2", 9, valid_from=10), REGISTRY)


@pytest.mark.parametrize("status", ["stale", "superseded", "retracted"])
def test_beliefs_that_are_no_longer_live_do_not_contradict(status):
    assert not contradicts(b("1", 1, status=status), b("2", 9), REGISTRY)


def test_a_suspect_belief_still_counts():
    assert contradicts(b("1", 1, status="suspect"), b("2", 9), REGISTRY)


def test_an_unregistered_predicate_is_an_error():
    with pytest.raises(KeyError):
        contradicts(b("1", 1, predicate="zzz"), b("2", 2, predicate="zzz"), REGISTRY)
