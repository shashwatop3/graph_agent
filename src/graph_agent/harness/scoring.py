"""Scoring a finished game: the metrics of the experiment spec, the same way for every system.

Where the numbers come from matters more than the formulas. Everything here is measured from the
engine's own records (the message log, when fields ignited, which waterings met fire) and the
oracle, never from what an agent says about itself. That is what lets a chat log, a vector memory
and a knowledge graph be compared on one scale.

Two kinds of metric
  * Game outcome, for every system:   fields saved, water wasted, how far lies spread, tokens,
                                      and what agents answer when asked a question (probes).
  * Belief handling, graph setups only: propagation precision and recall, false invalidations,
                                      false beliefs still held, how fast an imposter is isolated.
    These need a belief store to look inside. The baselines have none, so they are measured by
    their behaviour and by probes, which is exactly the comparison the project is about.
"""

import re
import statistics
from dataclasses import dataclass
from typing import TypedDict

from ..sim.comms import Claim, Message
from ..sim.game import Game
from ..sim.oracle import Oracle
from .backend import GraphBackend
from .game import GameResult
from .llm import ModelClient
from .pipeline import Exposure
from .types import AfterDay, Backend


class ProbeScores(TypedDict):
    probe_accuracy: float | None
    stale_leakage: float | None
    probes: int


class WaterUse(TypedDict):
    waterings: int
    water_wasted: int


class LieSpread(TypedDict):
    messages: int
    false_messages: int
    lies_relayed: int


class Isolation(TypedDict):
    isolated: float | None
    days_to_isolate: float | None


class Propagation(TypedDict):
    propagation_precision: float | None
    propagation_recall: float | None
    false_invalidations: int | None
    false_beliefs_remaining: int | None


class Totals(TypedDict):
    fields_saved: int
    fields: int
    days: int
    tokens_in: int
    tokens_out: int
    model_calls: int


class ScoreRow(Totals, WaterUse, LieSpread, Isolation, Propagation, ProbeScores):
    """One game's results: every metric, by name."""


WATERED = "you will water your fields today"  # what the water action replies when it succeeds

PROBE_SYSTEM = (
    "Answer with one whole number: the day fire first reaches the field you are asked about, "
    "or the single word never. Nothing else."
)


# ---- probes: ask every system the same question --------------------------------------------------


@dataclass
class Probe:
    day: int  # asked at the end of this day
    agent: int
    field_id: int
    answer: int | str  # a day, "never", or "?" when the reply had no number
    tokens_in: int = 0
    tokens_out: int = 0


def parse_answer(text: str) -> int | str:
    lowered = text.strip().lower()
    if lowered.startswith("never"):
        return "never"
    found = re.search(r"-?\d+", lowered)
    return int(found.group()) if found else "?"


def make_probe_hook(
    client: ModelClient, probes: list[Probe], budget: int, probe_days: set[int]
) -> AfterDay:
    """An `after_day` hook for run_game that asks each honest agent, on the given days, when fire
    will reach its first field that has not burnt yet. Answers are appended to `probes`."""

    def hook(game: Game, backend: Backend, day: int) -> None:
        if day not in probe_days:
            return
        for number in range(game.sim.world.config.n_agents):
            if number in game.net.imposters:
                continue
            unburnt = [
                f for f in game.sim.world.fields_of(number) if game.sim.fields[f].ignited_on is None
            ]
            if not unburnt:
                continue
            context = backend.context(number, day + 1, budget)
            question = (
                f"\n\nIt is the end of day {day}. On what day will fire first reach F{unburnt[0]}?"
            )
            reply = client.complete(
                PROBE_SYSTEM, [{"role": "user", "content": context + question}], []
            )
            probes.append(
                Probe(
                    day,
                    number,
                    unburnt[0],
                    parse_answer(reply.text),
                    reply.tokens_in,
                    reply.tokens_out,
                )
            )

    return hook


def score_probes(game: Game, probes: list[Probe]) -> ProbeScores:
    """Accuracy, and stale leakage: how often an agent that had been told something false about a
    field then answers with exactly that false value."""
    if not probes:
        return {"probe_accuracy": None, "stale_leakage": None, "probes": 0}
    correct = told_false = leaked = 0
    for p in probes:
        ignited = game.sim.fields[p.field_id].ignited_on
        truth = "never" if ignited is None else ignited
        correct += p.answer == truth
        false_days = {
            m.claim.day
            for m in game.net.log
            if m.receiver == p.agent
            and m.claim.field_id == p.field_id
            and m.day <= p.day
            and m.claim.day != truth
        }
        if false_days:
            told_false += 1
            leaked += p.answer in false_days
    return {
        "probe_accuracy": correct / len(probes),
        "stale_leakage": leaked / told_false if told_false else None,
        "probes": len(probes),
    }


# ---- outcome metrics (every system) --------------------------------------------------------------


def water_use(result: GameResult) -> WaterUse:
    """A watering is wasted if no fire reached any of that agent's fields on that day."""
    world = result.game.sim.world
    waterings = {
        (day, int(agent[1:]))
        for day, agent, turn in result.turns
        for name, _, output in turn.calls
        if name == "act" and output.endswith(WATERED)
    }
    met_fire = {
        (day_result.report.day, world.owner(f))
        for day_result in result.days
        for f in day_result.report.hit_while_watered
    }
    return {"waterings": len(waterings), "water_wasted": len(waterings - met_fire)}


def lie_spread(game: Game) -> LieSpread:
    """How far false information got. `lies_relayed` counts messages carrying a claim an imposter
    changed that were sent by an honest agent: the lie spreading on its own."""
    oracle = Oracle(game)
    return {
        "messages": len(game.net.log),
        "false_messages": len(oracle.false_messages()),
        "lies_relayed": sum(
            1 for m in game.net.log if m.altered_by and m.sender not in game.net.imposters
        ),
    }


# ---- belief-handling metrics (graph setups) ------------------------------------------------------


def isolation(game: Game, exposures: list[Exposure]) -> Isolation:
    """How quickly each imposter was distrusted by anybody."""
    imposters = sorted(game.net.imposters)
    if not imposters:
        return {"isolated": None, "days_to_isolate": None}
    first = {
        a: min((e.day for e in exposures if e.agent == f"A{a}"), default=None) for a in imposters
    }
    caught = [d for d in first.values() if d is not None]
    return {
        "isolated": len(caught) / len(imposters),
        "days_to_isolate": statistics.mean(caught) if caught else None,
    }


def propagation(game: Game, backend: Backend) -> Propagation:
    """Did each exposure remove support from exactly the beliefs it should have?

    For an exposure (viewer v distrusts agent a), the oracle says which claims lose all support: a
    claim whose every message to v, up to that day, passed through an agent v now distrusts. The
    store says which told beliefs it marked stale. Precision is how many of the store's were right;
    recall is how many of the oracle's the store found. A stale belief whose claim was actually
    true is a false invalidation.
    """
    if not isinstance(backend, GraphBackend):  # the baselines have no store to look inside
        return {
            "propagation_precision": None,
            "propagation_recall": None,
            "false_invalidations": None,
            "false_beliefs_remaining": None,
        }
    store = backend.store
    oracle = Oracle(game)
    exposed_by: dict[str, set[int]] = {}
    reported = matched = expected_total = false_invalidations = 0

    def lost(viewer_no: int, distrusted: set[int], day: int) -> set[tuple[int, int]]:
        by_claim: dict[tuple[int, int], list[Message]] = {}
        for m in game.net.log:
            if m.receiver == viewer_no and m.day <= day:
                by_claim.setdefault((m.claim.field_id, m.claim.day), []).append(m)
        return {c for c, ms in by_claim.items() if all(set(m.route) & distrusted for m in ms)}

    for e in backend.exposures:
        viewer_no, agent_no = int(e.viewer[1:]), int(e.agent[1:])
        before = set(exposed_by.setdefault(e.viewer, set()))
        exposed_by[e.viewer] = before | {agent_no}
        expected = lost(viewer_no, exposed_by[e.viewer], e.day) - lost(viewer_no, before, e.day)
        stale: set[tuple[int, int]] = set()
        for change in e.changes:
            if change.new_status != "stale":
                continue
            belief = store.belief(e.viewer, change.belief_id)
            if belief is None or belief.origin != "told":
                continue
            claim = (int(belief.subject[1:]), int(belief.value))
            stale.add(claim)
            false_invalidations += oracle.claim_is_true(Claim(*claim)) is True
        reported += len(stale)
        matched += len(stale & expected)
        expected_total += len(expected)

    remaining = 0
    for number in range(game.sim.world.config.n_agents):
        for belief in store.beliefs(f"A{number}", predicate="fire.arrival_day"):
            if belief.origin == "told" and belief.status in ("active", "suspect"):
                remaining += (
                    oracle.claim_is_true(Claim(int(belief.subject[1:]), int(belief.value))) is False
                )
    return {
        "propagation_precision": matched / reported if reported else None,
        "propagation_recall": matched / expected_total if expected_total else None,
        "false_invalidations": false_invalidations,
        "false_beliefs_remaining": remaining,
    }


# ---- everything together -------------------------------------------------------------------------


def score_game(result: GameResult, backend: Backend, probes: list[Probe] | None = None) -> ScoreRow:
    """One row of results for one game."""
    probes = probes or []
    steps = sum(t.steps for _, _, t in result.turns)
    base: Totals = {
        "fields_saved": result.fields_saved,
        "fields": result.game.sim.world.n_fields,
        "days": result.game.day,
        "tokens_in": result.tokens_in + sum(p.tokens_in for p in probes),
        "tokens_out": result.tokens_out + sum(p.tokens_out for p in probes),
        "model_calls": steps + len(probes),
    }
    return {
        **base,
        **water_use(result),
        **lie_spread(result.game),
        **isolation(result.game, backend.exposures),
        **propagation(result.game, backend),
        **score_probes(result.game, probes),
    }
