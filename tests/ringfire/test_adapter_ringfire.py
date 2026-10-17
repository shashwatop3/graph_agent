"""The Ring Fire adapter on its own (reference store, no simulator involved)."""

import pytest

from graph_agent.adapters import ringfire as rf
from graph_agent.stores.memory import MemoryStore

N = 6
FIELDS = [(f, f) for f in range(N)]  # one field per agent
RING = [(f, (f + 1) % N, 1) for f in range(N)]


@pytest.fixture
def store():
    store = MemoryStore()
    rf.setup_map(store, N, FIELDS, RING)
    return store


def message(sender, receiver, route, field, day, sent_on=0):
    return {
        "sender": sender,
        "receiver": receiver,
        "route": route,
        "day": sent_on,
        "claim": {"field_id": field, "day": day},
    }


def test_a_message_becomes_an_observation_with_its_route_and_a_told_belief(store):
    belief = rf.record_message(store, rf.Ids(), message(2, 3, [0, 1, 2], field=3, day=4))
    assert (belief.owner, belief.subject, belief.value, belief.origin) == ("A3", "F3", 4, "told")
    assert store.support_routes("A3", belief.id) == [("A0", "A1", "A2")]
    assert store.get("A4", belief.id) is None  # nobody else can see it


def test_hearing_the_same_claim_by_another_route_adds_a_route_to_the_same_belief(store):
    ids = rf.Ids()
    first = rf.record_message(store, ids, message(2, 3, [0, 1, 2], field=3, day=4))
    second = rf.record_message(store, ids, message(4, 3, [5, 4], field=3, day=4))
    assert first.id == second.id
    assert sorted(store.support_routes("A3", first.id)) == [("A0", "A1", "A2"), ("A5", "A4")]


def test_a_message_routed_through_a_distrusted_agent_is_seen_but_believed_by_nobody(store):
    ids = rf.Ids()
    belief = rf.record_message(
        store, ids, message(2, 3, [0, 1, 2], field=3, day=4), distrusted={"A1"}
    )
    assert belief is None and store.beliefs("A3") == []
    (seen,) = store.observations("A3", since_tick=0)
    assert seen.sender == "A2"  # it is in the inbox, with its route, just not a belief
    # the same claim by a route the agent does trust is believed as usual
    trusted = rf.record_message(
        store, ids, message(4, 3, [5, 4], field=3, day=4), distrusted={"A1"}
    )
    assert trusted is not None and trusted.value == 4


def test_evidence_is_a_route_less_observation_that_always_counts(store):
    belief = rf.record_evidence(store, rf.Ids(), {"day": 0, "field_id": 0}, 3)
    assert (belief.origin, belief.value) == ("observed", 0)
    assert store.support_routes("A3", belief.id) == [()]


def test_a_wrong_claim_is_refuted_by_evidence_and_its_sender_is_blamed(store):
    ids = rf.Ids()
    rf.record_message(store, ids, message(2, 3, [0, 1, 2], field=3, day=4))
    evidence = rf.record_evidence(store, ids, {"day": 3, "field_id": 3}, 3)
    blamed = rf.agents_to_distrust(store, "A3", evidence)
    assert [agent for agent, _ in blamed] == ["A2"]  # the direct sender, not the origin
    assert "day 4" in blamed[0][1] and "day 3" in blamed[0][1]


def test_a_correct_claim_blames_nobody(store):
    ids = rf.Ids()
    rf.record_message(store, ids, message(2, 3, [0, 1, 2], field=3, day=3))
    evidence = rf.record_evidence(store, ids, {"day": 3, "field_id": 3}, 3)
    assert rf.agents_to_distrust(store, "A3", evidence) == []


def test_a_claim_that_no_fire_confirms_expires_once_its_day_is_over(store):
    rf.record_message(store, rf.Ids(), message(1, 2, [1], field=4, day=2))
    assert rf.agents_with_expired_claims(store, "A2", today=1) == []  # day 2 not over yet
    assert [a for a, _ in rf.agents_with_expired_claims(store, "A2", today=2)] == ["A1"]


def test_a_claim_confirmed_by_evidence_does_not_expire(store):
    ids = rf.Ids()
    rf.record_message(store, ids, message(1, 2, [1], field=4, day=2))
    rf.record_evidence(store, ids, {"day": 2, "field_id": 4}, 2)
    assert rf.agents_with_expired_claims(store, "A2", today=5) == []


def test_forecast_is_arrival_plus_shortest_path_and_depends_on_its_evidence(store):
    ids = rf.Ids()
    seen = rf.record_evidence(store, ids, {"day": 0, "field_id": 0}, 3)
    forecast = rf.forecast_arrival(store, ids, "A3", target_field=3, tick=0)
    assert (forecast.value, forecast.origin, forecast.subject) == (3, "derived", "F3")
    assert store.dependents("A3", seen.id) == {forecast.id: 1}


def test_forecast_uses_the_earliest_of_several_fires_and_is_not_duplicated(store):
    ids = rf.Ids()
    rf.record_evidence(store, ids, {"day": 0, "field_id": 0}, 3)
    rf.record_evidence(store, ids, {"day": 2, "field_id": 2}, 3)  # closer to F3, but later
    again = rf.forecast_arrival(store, ids, "A3", 3, tick=2)
    assert again.value == 3  # min(0 + 3, 2 + 1)
    assert rf.forecast_arrival(store, ids, "A3", 3, tick=2).id == again.id


def test_a_revealed_hidden_edge_shortens_the_forecast(store):
    ids = rf.Ids()
    rf.record_evidence(store, ids, {"day": 0, "field_id": 0}, 3)
    before = rf.forecast_arrival(store, ids, "A3", 4, tick=0)
    rf.reveal_hidden_edge(store, 0, 4, 1)
    after = rf.forecast_arrival(store, ids, "A3", 4, tick=1)
    assert (before.value, after.value) == (4, 1)


def test_nothing_to_forecast_from_when_no_fire_is_known(store):
    assert rf.forecast_arrival(store, rf.Ids(), "A3", 3, tick=0) is None


def test_a_forecast_that_disagrees_with_a_told_claim_is_found_as_a_conflict(store):
    ids = rf.Ids()
    told = rf.record_message(store, ids, message(2, 3, [0, 1, 2], field=3, day=4))
    rf.record_evidence(store, ids, {"day": 0, "field_id": 0}, 3)
    forecast = rf.forecast_arrival(store, ids, "A3", 3, tick=0)
    assert [b.id for b in store.conflicts("A3", told.id, rf.PREDICATES)] == [forecast.id]
