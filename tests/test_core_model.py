from typing import get_args

import pytest
from pydantic import ValidationError

from graph_agent.core.model import (
    EDGE_RULES,
    Action,
    Agent,
    Belief,
    Correction,
    Edge,
    EdgeKind,
    Entity,
    Observation,
    check_edge,
    visible,
)


def test_there_are_nine_relationship_kinds_each_with_a_rule():
    assert len(get_args(EdgeKind)) == 9 and set(EDGE_RULES) == set(get_args(EdgeKind))


def test_check_edge_accepts_the_right_types_and_rejects_the_wrong_ones():
    obs = Observation(id="O1", kind="message", received_by="A1")
    belief = Belief(id="B1", owner="A1", subject="E1", predicate="p", value=1)
    action = Action(id="X1", owner="A1", type="t")
    check_edge(Edge(kind="SUPPORTS", src="O1", dst="B1"), obs, belief)
    check_edge(Edge(kind="DERIVED_FROM", src="X1", dst="B1"), action, belief)  # action ok
    with pytest.raises(ValueError):
        check_edge(Edge(kind="DERIVED_FROM", src="O1", dst="B1"), obs, belief)


def test_unknown_fields_and_bad_confidence_are_rejected():
    with pytest.raises(ValidationError):
        Agent(id="A1", colour="red")
    with pytest.raises(ValidationError):
        Belief(id="B1", owner="A1", subject="E1", predicate="p", value=1, confidence=1.5)


def test_an_observation_gets_a_content_hash_that_depends_on_its_payload():
    one = Observation(id="O1", kind="sensor", received_by="A1", payload={"x": 1})
    same = Observation(id="O2", kind="sensor", received_by="A1", payload={"x": 1})
    other = Observation(id="O3", kind="sensor", received_by="A1", payload={"x": 2})
    assert one.hash == same.hash != other.hash


def test_visibility_rules():
    belief = Belief(id="B1", owner="A1", subject="E1", predicate="p", value=1)
    obs = Observation(id="O1", kind="message", received_by="A1")
    own = Correction(
        id="C1",
        type="exposure",
        issued_by="engine",
        target="A9",
        tick=1,
        observer="A1",
    )
    everyone = Correction(id="C2", type="retraction", issued_by="engine", target="B1", tick=1)
    assert visible("A1", belief) and not visible("A2", belief)
    assert visible("A1", obs) and not visible("A2", obs)
    assert visible("A1", own) and not visible("A2", own)
    assert visible("A2", everyone)
    assert visible("A2", Agent(id="A1")) and visible("A2", Entity(id="E1", type="t"))
