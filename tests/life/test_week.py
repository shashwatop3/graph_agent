"""The week generator: seed 0 is the fixed week; other seeds are varied, scored the same way."""

import dataclasses
import json
from pathlib import Path

import pytest

from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.packs.life.run import run_life
from graph_agent.packs.life.standin import life_team
from graph_agent.packs.life.week import Week, make_week, minutes
from graph_agent.packs.life.world import LifeWorld, script

FIXED = Path(__file__).with_name("fixed_week.json")


def test_seed_zero_is_the_fixed_week_mail_for_mail():
    # the recorded runs replay from the model cache only if every prompt renders as before
    fixed = json.loads(FIXED.read_text())
    week = make_week(0)
    assert week == Week()
    now = json.loads(json.dumps([dataclasses.asdict(m) for m in script(week)]))
    assert now == fixed["script"]
    assert json.loads(json.dumps(week.entities())) == fixed["entities"]


def test_a_seed_always_draws_the_same_week_and_seeds_differ():
    assert make_week(7) == make_week(7)
    weeks = {make_week(seed) for seed in range(1, 30)}
    assert len(weeks) == 29
    assert {w.moved_to is None for w in weeks} == {True, False}  # some flights never move
    assert {w.deck_moved_to is None for w in weeks} == {True, False}
    assert {w.scam_airline for w in weeks} > {None}
    assert len({w.on_old_card for w in weeks}) > 3


@pytest.mark.parametrize("seed", range(1, 30))
def test_a_drawn_week_is_consistent(seed):
    w = make_week(seed)
    if w.moved_to is not None:
        assert minutes(w.moved_to) > minutes(w.departs)
        assert w.moved_at <= (minutes(w.departs) // 1440) * 2  # said before the first flight
    assert w.cards[0] != w.cards[1] and w.on_old_card
    # every mail is about things the week has
    entities = w.entities()
    for mail in script(w):
        assert all(e in entities for e in mail.about), mail
        assert all(subject in entities for subject, _, _ in mail.gold), mail
    world = LifeWorld(w)
    assert world.booking(w.booking)["flight"] == w.flight


@pytest.mark.parametrize("case", ["travel", "promises", "money", "week"])
def test_the_stand_in_team_leaves_every_drawn_week_right(case):
    for seed in range(1, 13):
        run = run_life(case, life_team(), seed=seed)
        assert all(run.checks.values()), (seed, run.checks)
        assert run.score["unsafe_proposals"] == 0
        assert run.score["honest_quarantined"] == 0


def test_the_checks_are_not_free_a_team_that_does_nothing_fails_them():
    def idle() -> ScriptedModel:
        return ScriptedModel(lambda *a: ModelReply(text="done"), model="idle")

    for seed in range(1, 13):
        run = run_life("week", idle(), seed=seed)
        assert not all(run.checks.values()), seed


def test_a_week_with_a_flight_that_never_moves_wants_the_clashing_call_moved():
    seed = next(s for s in range(1, 100) if make_week(s).moved_to is None)
    run = run_life("travel", life_team(), seed=seed)
    (check,) = [k for k in run.checks if "call with Dana" in k]
    assert "moved out of the travel window" in check and run.checks[check]
    assert run.world.events["ev-dana-call"].start != make_week(seed).call
