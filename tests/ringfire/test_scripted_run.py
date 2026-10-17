"""End to end with no LLM: scripted scenario -> simulator -> adapter -> store, on every store.

The same scripts run on the in-memory, FalkorDB and Postgres stores and must produce exactly the
same exposures and the same changes to beliefs. The oracle (built from the engine's logs only) says
which beliefs should have lost support, and the store's answer is checked against it.
"""

from pathlib import Path

import pytest

from graph_agent.packs.ringfire.benchmark.scripted import play_scripted
from graph_agent.packs.ringfire.sim.oracle import Oracle
from graph_agent.packs.ringfire.sim.scenario import load_scenario
from graph_agent.stores.memory import MemoryStore
from stores_param import STORES

SCENARIOS = Path(__file__).parents[1] / "scenarios"


@pytest.fixture(params=STORES)
def store(request):
    store = request.param()
    yield store
    store.close()


def summary(exposures):
    """Everything about the exposures that must be identical across stores."""
    return [
        (e.viewer, e.agent, e.day, [(c.belief_id, c.new_status, c.path_len) for c in e.changes])
        for e in exposures
    ]


def test_a_biased_relay_is_caught_when_the_fire_arrives(store):
    exposures, game = play_scripted(load_scenario(SCENARIOS / "bias_chain.json"), store)
    # A3 got "day 4" from A2 and A4 got it from A3. Evidence on day 3 refutes both, and each
    # blames whoever told it directly.
    assert [(e.viewer, e.agent, e.day) for e in exposures] == [
        ("A3", "A2", 3),
        ("A4", "A3", 3),
    ]
    assert all(len(e.changes) == 1 and e.changes[0].new_status == "stale" for e in exposures)


def test_the_stores_exposures_match_the_oracles_view_of_what_depends_on_whom(store):
    exposures, game = play_scripted(load_scenario(SCENARIOS / "bias_chain.json"), store)
    oracle = Oracle(game)
    for exposure in exposures:
        agent = int(exposure.agent[1:])
        viewer = int(exposure.viewer[1:])
        # messages this viewer received whose route includes the distrusted agent
        affected = [m for m in oracle.lost_if_exposed(agent) if m.receiver == viewer]
        # each of them was the only support of one belief, so exactly that many went stale
        assert len(affected) == len(exposure.changes) == 1
        assert all(m.altered_by for m in affected)  # and each really was tainted by an imposter


def test_a_false_alarm_is_caught_when_its_day_passes_without_fire(store):
    exposures, _ = play_scripted(load_scenario(SCENARIOS / "false_alarm.json"), store)
    # A1 told A2 "fire reaches F4 on day 2". By the end of day 2 there is no such fire.
    assert [(e.viewer, e.agent, e.day) for e in exposures] == [("A2", "A1", 2)]
    assert exposures[0].changes[0].new_status == "stale"


@pytest.mark.parametrize("name", ["bias_chain.json", "false_alarm.json"])
def test_every_store_gives_identical_results(store, name):
    scenario = load_scenario(SCENARIOS / name)
    reference = MemoryStore()
    expected = summary(play_scripted(scenario, reference)[0])
    assert summary(play_scripted(scenario, store)[0]) == expected
