from pathlib import Path

from graph_agent.packs.ringfire.sim.comms import Claim
from graph_agent.packs.ringfire.sim.oracle import Oracle
from graph_agent.packs.ringfire.sim.scenario import load_scenario, run_scenario

SCENARIOS = Path(__file__).parents[1] / "scenarios"


def test_bias_chain_scenario_has_the_expected_outcome():
    game = run_scenario(load_scenario(SCENARIOS / "bias_chain.json"))
    oracle = Oracle(game)
    log = game.net.log
    assert [m.sender for m in log] == [0, 1, 2, 3]
    assert [m.route for m in log] == [(0,), (0, 1), (0, 1, 2), (0, 1, 2, 3)]
    # agent 2 shifted the day, so its message and the honest relay after it are wrong
    assert [m.claim.day for m in log] == [3, 3, 4, 4]
    assert [m.id for m in oracle.tainted_messages()] == [2, 3]
    assert [m.id for m in oracle.false_messages()] == [2, 3]
    assert [m.id for m in oracle.lost_if_exposed(2)] == [2, 3]
    assert oracle.claim_is_true(Claim(3, 3)) is True


def test_scenarios_are_deterministic():
    spec = load_scenario(SCENARIOS / "bias_chain.json")
    assert run_scenario(spec).net.log == run_scenario(spec).net.log
