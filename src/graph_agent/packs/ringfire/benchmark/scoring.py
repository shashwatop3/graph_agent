"""Scoring a finished game: the metrics of the experiment spec, the same way for every system.

Where the numbers come from matters more than the formulas. Everything here is measured from the
engine's own records (the message log, when fields ignited, which waterings met fire) and the
oracle, never from what an agent says about itself. That is what lets a chat log, a vector memory
and a knowledge graph be compared on one scale.

Two kinds of metric
  * Game outcome, for every system:   fields saved (never burnt), ignitions (fires that took,
                                      counting a field each time it burns), fires put out, water
                                      wasted, how far lies spread, tokens, and what agents answer
                                      when asked a question (probes).
  * Belief handling, graph setups only: propagation precision and recall, false invalidations,
                                      false beliefs still held, how fast an imposter is isolated.
    These need a belief store to look inside. The baselines have none, so they are measured by
    their behaviour and by probes, which is exactly the comparison the project is about.
"""

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypedDict

from graph_agent.core.compiler import estimate_tokens
from graph_agent.core.model import Belief
from graph_agent.core.store import Exposure, Store
from graph_agent.harness.llm import ModelClient
from graph_agent.harness.trace import NO_TRACE, Trace

from .. import adapter as ringfire
from ..sim.comms import Claim, Message
from ..sim.field import FieldState
from ..sim.game import Game
from ..sim.oracle import Oracle
from .backend import GraphBackend
from .game import GameResult
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
    # of every (honest agent, imposter) pair, the share where the honest agent distrusts the
    # imposter by the end: how far the honest agents converged on who the liars are
    liar_coverage: float | None
    honest_distrusted: int | None  # (honest agent, honest agent) pairs wrongly distrusted
    warnings: int | None  # warnings sent between agents (group correction)


class Totals(TypedDict):
    # honest_ignitions + waste_penalty x water_wasted: the one number to minimise (lower is
    # better). Only honest agents' fields count: nobody protects an imposter's fields.
    loss: float
    honest_ignitions: int
    fields_saved: int
    ignitions: int  # every time a field caught fire, start fires included
    fires_put_out: int  # every time fire reached a field on a day its owner watered
    fields: int
    days: int
    tokens_in: int
    tokens_out: int
    model_calls: int


class ScoreRow(Totals, WaterUse, LieSpread, Isolation, Propagation, ProbeScores):
    """One game's results: every metric, by name."""


_LIVE = ("active", "suspect")
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
    client: ModelClient,
    probes: list[Probe],
    budget: int,
    probe_days: set[int],
    trace: Trace = NO_TRACE,
) -> AfterDay:
    """An `after_day` hook for run_game that asks each honest agent, on the given days, when fire
    will next reach its first field that is not burning or burnt now. Answers are appended to
    `probes`."""

    def hook(game: Game, backend: Backend, day: int) -> None:
        if day not in probe_days:
            return
        for number in range(game.sim.world.config.n_agents):
            if number in game.net.imposters:
                continue
            unburnt = [
                f
                for f in game.sim.world.fields_of(number)
                if game.sim.fields[f].state is FieldState.UNBURNT
            ]
            if not unburnt:
                continue
            context = backend.context(number, day + 1, budget)
            question = (
                f"\n\nIt is the end of day {day}. On what day will fire first reach F{unburnt[0]}?"
            )
            if game.sim.world.config.horizon is not None:  # a long game: fire can come back
                question = (
                    f"\n\nIt is the end of day {day}. On what day will fire next reach "
                    f"F{unburnt[0]}? Say never if not before the game ends."
                )
            trace.bind(agent=f"A{number}")
            reply = client.complete(
                PROBE_SYSTEM, [{"role": "user", "content": context + question}], []
            )
            trace.unbind("agent")
            trace.emit(
                "probe",
                agent=f"A{number}",
                field=unburnt[0],
                asked_day=day,
                reply=reply.text,
                answer=parse_answer(reply.text),
                context_tokens=estimate_tokens(context),
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


def probe_truth(game: Game, probe: Probe) -> int | str:
    """The right answer: the first day after the question on which the field caught fire."""
    ignited = Oracle(game).next_ignition(probe.field_id, after=probe.day)
    return "never" if ignited is None else ignited


def score_probes(game: Game, probes: list[Probe]) -> ProbeScores:
    """Accuracy, and stale leakage: how often an agent that had been told something false about a
    field then answers with exactly that false value."""
    if not probes:
        return {"probe_accuracy": None, "stale_leakage": None, "probes": 0}
    correct = told_false = leaked = 0
    for p in probes:
        truth = probe_truth(game, p)
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


def as_claim(belief: Belief) -> Claim | None:
    """The claim an arrival belief makes, or None if it names no day: an agent can assert
    anything, such as the value "unknown"."""
    value = belief.value
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Claim(int(belief.subject[1:]), int(value))
    except ValueError:
        return None


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


def graph_parts(backend: Backend) -> tuple[Store, set[tuple[str, str]], int] | None:
    """(store, the (viewer, agent) distrust pairs, warnings sent) of a graph system, or None for a
    baseline. A frame run (packs/ringfire.py) provides the same through `graph_parts()`."""
    if isinstance(backend, GraphBackend):
        return backend.store, backend.pipeline.exposed, len(backend.pipeline.warnings)
    parts: Callable[[], tuple[Store, set[tuple[str, str]], int]] | None = getattr(
        backend, "graph_parts", None
    )
    return parts() if parts is not None else None


def propagation(game: Game, backend: Backend) -> Propagation:
    """Did each exposure remove support from exactly the beliefs it should have?

    For an exposure (viewer v distrusts agent a), the oracle says which claims lose all support: a
    claim whose every message to v, up to that day, passed through an agent v now distrusts. The
    store says which told beliefs it marked stale. Precision is how many of the store's were right;
    recall is how many of the oracle's the store found. A stale belief whose claim was actually
    true is a false invalidation.
    """
    parts = graph_parts(backend)
    if parts is None:  # the baselines have no store to look inside
        return {
            "propagation_precision": None,
            "propagation_recall": None,
            "false_invalidations": None,
            "false_beliefs_remaining": None,
            "liar_coverage": None,
            "honest_distrusted": None,
            "warnings": None,
        }
    store, distrust_pairs, n_warnings = parts
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
            claim = as_claim(belief)
            if claim is None:
                continue
            stale.add((claim.field_id, claim.day))
            false_invalidations += oracle.claim_is_true(claim) is True
        reported += len(stale)
        matched += len(stale & expected)
        expected_total += len(expected)

    remaining = 0
    for number in range(game.sim.world.config.n_agents):
        for belief in store.beliefs(f"A{number}", predicate="fire.arrival_day"):
            claim = as_claim(belief)
            if claim is not None and belief.origin == "told" and belief.status in _LIVE:
                remaining += oracle.claim_is_true(claim) is False
    imposters = set(game.net.imposters)
    honest = [n for n in range(game.sim.world.config.n_agents) if n not in imposters]
    distrusts = {(int(v[1:]), int(a[1:])) for v, a in distrust_pairs}
    pairs = len(honest) * len(imposters)
    return {
        "propagation_precision": matched / reported if reported else None,
        "propagation_recall": matched / expected_total if expected_total else None,
        "false_invalidations": false_invalidations,
        "false_beliefs_remaining": remaining,
        "liar_coverage": (
            sum(1 for v, a in distrusts if v in honest and a in imposters) / pairs
            if pairs
            else None
        ),
        "honest_distrusted": sum(1 for v, a in distrusts if v in honest and a not in imposters),
        "warnings": n_warnings,
    }


# ---- everything together -------------------------------------------------------------------------


def score_game(result: GameResult, backend: Backend, probes: list[Probe] | None = None) -> ScoreRow:
    """One row of results for one game."""
    probes = probes or []
    steps = sum(t.steps for _, _, t in result.turns)
    water = water_use(result)
    ignitions = sum(len(f.ignitions) for f in result.game.sim.fields)
    honest_ignitions = sum(
        len(f.ignitions) for f in result.game.sim.fields if f.owner not in result.game.net.imposters
    )
    penalty = result.game.sim.rules.waste_penalty
    base: Totals = {
        "loss": honest_ignitions + penalty * water["water_wasted"],
        "honest_ignitions": honest_ignitions,
        "fields_saved": result.fields_saved,
        "ignitions": ignitions,
        "fires_put_out": sum(len(d.report.hit_while_watered) for d in result.days),
        "fields": result.game.sim.world.n_fields,
        "days": result.game.day,
        "tokens_in": result.tokens_in + sum(p.tokens_in for p in probes),
        "tokens_out": result.tokens_out + sum(p.tokens_out for p in probes),
        "model_calls": steps + len(probes),
    }
    return {
        **base,
        **water,
        **lie_spread(result.game),
        **isolation(result.game, backend.exposures),
        **propagation(result.game, backend),
        **score_probes(result.game, probes),
    }


def trace_final_state(
    trace: Trace, result: GameResult, backend: Backend, probes: list[Probe], row: ScoreRow
) -> None:
    """Write what a finished game ended up with: each probe next to the truth, every arrival belief
    each agent holds next to whether the oracle says it is true, and the score."""
    game = result.game
    for p in probes:
        truth = probe_truth(game, p)
        trace.emit(
            "probe_scored",
            agent=f"A{p.agent}",
            asked_day=p.day,
            field=p.field_id,
            answer=p.answer,
            truth=truth,
            correct=p.answer == truth,
        )
    parts = graph_parts(backend)
    if parts is not None:
        store = parts[0]
        oracle = Oracle(game)
        for number in range(game.sim.world.config.n_agents):
            viewer = ringfire.agent_id(number)
            for belief in store.beliefs(viewer, predicate=ringfire.ARRIVAL):
                claim = as_claim(belief)
                truth = None if claim is None else oracle.claim_is_true(claim)
                trace.emit(
                    "beliefs",
                    agent=viewer,
                    belief=belief.id,
                    subject=belief.subject,
                    value=belief.value,
                    origin=belief.origin,
                    status=belief.status,
                    support_routes=belief.support_routes,
                    claim_true=truth,
                    routes=[list(r) for r in store.support_routes(viewer, belief.id)],
                    created_tick=belief.created_tick,
                    sources=store.sources(viewer, belief.id),  # what it is DERIVED_FROM
                )
    trace.emit("score", **row)
