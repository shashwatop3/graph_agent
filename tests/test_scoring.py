"""The scorer, checked against games whose right answers can be worked out by hand."""

from pathlib import Path

import pytest

from fake_agent import honest_agent
from fake_baseline_agent import log_reader
from graph_agent.core.model import Belief
from graph_agent.harness.backend import GraphBackend
from graph_agent.harness.baselines import SharedLogBackend
from graph_agent.harness.game import run_game
from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.harness.scoring import (
    Probe,
    as_claim,
    make_probe_hook,
    parse_answer,
    score_game,
    score_probes,
)
from graph_agent.sim.comms import Claim
from graph_agent.sim.scenario import build_game, load_scenario
from graph_agent.stores.memory import MemoryStore

SCENARIO = load_scenario(Path(__file__).parent / "scenarios" / "live_ring.json")


def graph_game(**kw):
    backend = GraphBackend(MemoryStore())
    return run_game(SCENARIO, backend, honest_agent(6), **kw), backend


# ---- probes -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [("4", 4), ("  Day 7. ", 7), ("Never", "never"), ("never reaches", "never"), ("no idea", "?")],
)
def test_answers_are_parsed_into_a_day_or_never(text, expected):
    assert parse_answer(text) == expected


def test_accuracy_counts_answers_that_match_when_fire_really_arrived():
    result, _ = graph_game()
    game = result.game  # fire reaches field f on day f
    probes = [Probe(2, 3, 3, 3), Probe(2, 4, 4, 9), Probe(2, 5, 5, "never")]
    scored = score_probes(game, probes)
    assert scored["probe_accuracy"] == pytest.approx(1 / 3)
    assert scored["probes"] == 3


def test_stale_leakage_is_answering_with_exactly_the_false_value_one_was_told():
    result, _ = graph_game()
    game = result.game
    told = [m for m in game.net.log if m.altered_by]
    victim = told[0]  # a shifted claim: this receiver was told a wrong day for this field
    wrong = victim.claim.day
    leak = Probe(victim.day + 1, victim.receiver, victim.claim.field_id, wrong)
    resisted = Probe(victim.day + 1, victim.receiver, victim.claim.field_id, wrong + 50)
    assert score_probes(game, [leak])["stale_leakage"] == 1.0
    assert score_probes(game, [resisted])["stale_leakage"] == 0.0
    assert score_probes(game, [])["probe_accuracy"] is None


def test_probes_are_asked_of_honest_agents_about_a_field_that_has_not_burnt():
    probes = []
    client = ScriptedModel(lambda s, m, t: ModelReply(text="3", tokens_in=7, tokens_out=1))
    hook = make_probe_hook(client, probes, budget=1000, probe_days={1})
    run_game(SCENARIO, GraphBackend(MemoryStore()), honest_agent(6), after_day=hook)
    assert probes and {p.day for p in probes} == {1}
    game = build_game(SCENARIO)
    assert 2 not in {p.agent for p in probes}  # the imposter is not asked
    assert all(
        p.field_id >= 2 for p in probes
    )  # only fields that had not burnt by the end of day 1
    assert game.sim.world.owner(probes[0].field_id) == probes[0].agent


# ---- game outcome -----------------------------------------------------------------------------


def test_a_game_row_has_the_outcome_metrics_for_any_system():
    result = run_game(SCENARIO, SharedLogBackend(), log_reader(6))
    row = score_game(result, SharedLogBackend())
    assert row["fields"] == 6 and 0 <= row["fields_saved"] <= 6
    assert row["messages"] == len(result.game.net.log)
    assert row["lies_relayed"] > 0  # a log has nothing that stops honest agents relaying a lie
    assert row["model_calls"] == sum(t.steps for _, _, t in result.turns)
    assert row["propagation_precision"] is None  # a log has no beliefs to look inside


def test_water_is_wasted_when_no_fire_arrives_that_day():
    result, backend = graph_game()
    row = score_game(result, backend)
    assert row["waterings"] >= row["water_wasted"] >= 0
    # the stand-in only waters on the day a claim says fire arrives; shifted claims cost water
    assert row["waterings"] > 0


# ---- belief handling (graph) ------------------------------------------------------------------


def test_propagation_matches_the_oracle_exactly_when_the_layer_works():
    result, backend = graph_game()
    row = score_game(result, backend)
    assert row["propagation_precision"] == 1.0
    assert row["propagation_recall"] == 1.0
    assert row["false_invalidations"] == 0
    assert row["isolated"] == 1.0 and row["days_to_isolate"] == 1


def test_no_false_beliefs_remain_and_no_lie_is_passed_on_in_the_graph_setup():
    result, backend = graph_game()
    row = score_game(result, backend)
    assert row["false_messages"] > 0  # the imposter did lie
    assert row["false_beliefs_remaining"] == 0  # and nobody still holds one of those lies
    assert row["lies_relayed"] == 0  # A1 stopped believing A2, so it never passed a lie on


def test_without_a_graph_the_same_lie_keeps_travelling():
    log = run_game(SCENARIO, SharedLogBackend(), log_reader(6))
    graph, backend = graph_game()
    assert (
        score_game(log, SharedLogBackend())["lies_relayed"]
        > score_game(graph, backend)["lies_relayed"]
    )


def test_a_wrong_exposure_shows_up_as_a_false_invalidation():
    """Force the store to distrust an honest agent: its true claims become stale, and the scorer
    must call that a false invalidation."""
    result, backend = graph_game()
    store = backend.store
    honest_claims = [
        m for m in result.game.net.log if not m.altered_by and m.route and m.receiver == 3
    ]
    assert honest_claims
    sender = honest_claims[0].sender
    from graph_agent.harness.pipeline import Exposure

    changes = store.expose("A3", f"A{sender}", tick=99, reason="mistaken")
    backend.exposures.append(Exposure("A3", f"A{sender}", 99, "mistaken", changes))
    row = score_game(result, backend)
    assert row["false_invalidations"] >= 1
    assert row["propagation_precision"] <= 1.0


def test_every_graph_store_is_scored_identically():
    first, first_backend = graph_game()
    second, second_backend = graph_game()
    assert score_game(first, first_backend) == score_game(second, second_backend)


def test_a_belief_with_no_day_in_it_is_skipped_not_a_crash():
    def belief(value):
        return Belief(id="B1", owner="A1", subject="F3", predicate="fire.arrival_day", value=value)

    assert as_claim(belief("unknown")) is None
    assert as_claim(belief(None)) is None
    assert as_claim(belief(4)) == Claim(3, 4) and as_claim(belief("4")) == Claim(3, 4)
