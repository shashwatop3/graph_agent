"""Private evidence: fire in a field is shown only to its owner and to agents told about it.

This is the rule that gives messages something to carry. With public evidence every agent always
knows where the fire is and an isolated agent can work everything out alone.
"""

from pathlib import Path

import pytest
from fake_agent import honest_agent
from fake_baseline_agent import log_reader

from graph_agent.packs.ringfire import adapter as rf
from graph_agent.packs.ringfire.benchmark.backend import GraphBackend
from graph_agent.packs.ringfire.benchmark.baselines import (
    BASELINES,
    IsolatedBackend,
    SharedLogBackend,
)
from graph_agent.packs.ringfire.benchmark.experiment import Knobs, run_experiment
from graph_agent.packs.ringfire.benchmark.game import run_game
from graph_agent.packs.ringfire.benchmark.pipeline import Pipeline
from graph_agent.packs.ringfire.sim.comms import Claim
from graph_agent.packs.ringfire.sim.scenario import build_game, load_scenario
from graph_agent.stores.memory import MemoryStore

BASE = load_scenario(Path(__file__).parents[1] / "scenarios" / "live_ring.json")
PRIVATE = {**BASE, "evidence": "private"}


# ---- the engine -------------------------------------------------------------------------------


def test_public_evidence_goes_to_everyone():
    game = build_game(BASE)
    assert game.audience(3, 0) == tuple(range(6))


def test_private_evidence_goes_to_the_owner_and_to_anyone_told_about_that_field():
    game = build_game(PRIVATE)
    assert game.audience(3, 0) == (3,)  # only the owner
    game.send(0, 1, Claim(field_id=3, day=3))  # A1 is told something about F3
    game.send(4, 5, Claim(field_id=0, day=0))  # a claim about a different field
    assert game.audience(3, 0) == (1, 3)
    assert game.audience(0, 0) == (0, 5)


def test_the_starting_fire_is_shown_only_to_its_owner_in_private_mode():
    game = build_game(PRIVATE)
    (start,) = game.step().evidence
    assert start.field_id == 0 and start.audience == (0,)


def test_a_claim_made_later_does_not_reach_back_in_time():
    game = build_game(PRIVATE)
    game.step()
    game.step()  # it is now day 2
    game.send(0, 1, Claim(3, 3))  # A1 is told about F3 on day 2
    assert game.audience(3, 1) == (3,)  # on day 1 it was not yet told
    assert game.audience(3, 2) == (1, 3)


# ---- the graph pipeline -----------------------------------------------------------------------


def test_an_agent_not_in_the_audience_has_no_evidence_in_its_graph():
    store = MemoryStore()
    pipeline = Pipeline(store)
    game = build_game(PRIVATE)
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    assert [b.value for b in store.beliefs("A0", predicate=rf.ARRIVAL)] == [0]
    for other in ("A1", "A2", "A3", "A4", "A5"):
        assert store.beliefs(other) == []


def test_a_late_claim_about_a_field_that_already_burnt_is_checked_at_once():
    store = MemoryStore()
    pipeline = Pipeline(store)
    game = build_game(PRIVATE)
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    pipeline.day(game, game.step())  # F0 burnt on day 0, shown only to A0
    lie = game.send(1, 2, Claim(field_id=0, day=5))  # A2 is told F0 burns on day 5
    pipeline.message(lie)
    # the engine shows A2 the truth at once, so it can tell the claim is false and who said it
    assert [e.agent for e in pipeline.exposures if e.viewer == "A2"] == ["A1"]
    assert {
        b.value for b in store.beliefs("A2", predicate=rf.ARRIVAL) if b.origin == "observed"
    } == {0}


# ---- the baselines ----------------------------------------------------------------------------


def test_b0_in_private_mode_sees_only_its_own_fields_evidence():
    backend = IsolatedBackend()
    run_game(PRIVATE, backend, log_reader(6, can_send=False), max_days=3)
    assert "PUBLISHED: field F0" in backend.context(0, 3, 4000)
    assert "PUBLISHED" not in backend.context(4, 3, 4000)  # A4 was never told anything


def test_the_shared_log_shows_every_message_but_only_the_evidence_you_may_see():
    backend = SharedLogBackend()
    run_game(PRIVATE, backend, log_reader(6), max_days=3)
    for agent in range(6):
        context = backend.context(agent, 3, 4000)
        assert "told" in context  # every message is on the shared log
        for field, line in backend._evidence_line.items():  # the fields that had burnt by then
            seen = f"PUBLISHED: field F{field} caught" in context
            assert seen == (agent in backend.audience[line])


# ---- the point of the change ------------------------------------------------------------------


def accuracy(system, scenario_evidence, seeds=(0, 1, 2)):
    def client(system, knobs):
        if system.startswith("graph"):
            return honest_agent(knobs.n_agents)
        return log_reader(knobs.n_agents, can_send=system != "B0")

    rows = run_experiment(
        [system],
        [Knobs(n_agents=8, evidence=scenario_evidence)],
        list(seeds),
        client,
        probe_days=(2, 4),
    )
    values = [r["probe_accuracy"] for r in rows if r["probe_accuracy"] is not None]
    return sum(values) / len(values)


def test_with_public_evidence_isolated_agents_are_already_perfect():
    assert accuracy("B0", "public") == 1.0


def test_with_private_evidence_isolated_agents_can_no_longer_work_it_out():
    assert accuracy("B0", "private") < 0.5


def test_with_private_evidence_messages_carry_information_so_coordination_pays():
    isolated = accuracy("B0", "private")
    assert accuracy("graph-memory", "private") > isolated
    assert accuracy("B1", "private") > isolated


@pytest.mark.parametrize("system", ["graph-memory", "B0", "B1", "B2", "B3"])
def test_every_system_still_plays_a_whole_private_game(system):
    rows = run_experiment(
        [system],
        [Knobs(n_agents=6)],
        [0],
        lambda s, k: honest_agent(6) if s.startswith("graph") else log_reader(6, s != "B0"),
    )
    assert rows[0]["fields"] == 6


# ---- global versus own-inbox logs --------------------------------------------------------------


def test_the_own_inbox_log_shows_only_messages_the_agent_sent_or_received():
    backend = BASELINES["B1o"]()
    run_game(PRIVATE, backend, log_reader(6), max_days=3)
    context = backend.context(3, 3, 4000)
    told = [line for line in context.splitlines() if " told " in line]
    assert told  # it does see its own conversations
    assert all("A3" in line.split(" that ")[0] for line in told)  # and nobody else's


def test_the_global_log_shows_more_than_the_own_inbox_log():
    own, shared = BASELINES["B1o"](), BASELINES["B1"]()
    run_game(PRIVATE, own, log_reader(6), max_days=3)
    run_game(PRIVATE, shared, log_reader(6), max_days=3)
    assert len(shared.readable(3)) > len(own.readable(3))
    assert own.name == "B1-shared-log-own" and shared.name == "B1-shared-log"


def test_the_own_inbox_baselines_are_not_given_more_information_than_graph_agents():
    """The own-inbox log and a graph agent are shown the same facts: what they were told and what
    they are entitled to see. Only the way it is organised differs."""
    own, graph = BASELINES["B1o"](), GraphBackend(MemoryStore())
    own_result = run_game(PRIVATE, own, log_reader(6), max_days=3)
    run_game(PRIVATE, graph, honest_agent(6), max_days=3)
    received = {(m.sender, m.receiver) for m in own_result.game.net.log if m.receiver == 3}
    assert received  # A3 was told things, and the log shows each of those messages
    context = own.context(3, 3, 4000)
    for sender, _ in received:
        assert f"A{sender} told A3" in context
