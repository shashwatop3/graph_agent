"""The compiled context: what an agent is actually shown.

Snapshot tests compare against files in tests/snapshots. To accept a deliberate change, run
    UPDATE_SNAPSHOTS=1 uv run pytest tests/test_compiler.py
and read the diff of the snapshot files before committing it.
"""

import os
from pathlib import Path

import pytest

from graph_agent.core.compiler import compile_context, estimate_tokens
from graph_agent.core.model import Action, Edge
from graph_agent.packs.ringfire import adapter as rf
from graph_agent.packs.ringfire.benchmark.scripted import play_scripted
from graph_agent.packs.ringfire.sim.scenario import load_scenario
from graph_agent.stores.memory import MemoryStore
from stores_param import STORES

HERE = Path(__file__).parent
SCENARIOS = HERE / "scenarios"
SNAPSHOTS = HERE / "snapshots"


def assert_snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("UPDATE_SNAPSHOTS") or not path.exists():
        path.write_text(text + "\n")
    assert text + "\n" == path.read_text(), f"{name} changed; see {path}"


def played(store, scenario="bias_chain.json"):
    play_scripted(load_scenario(SCENARIOS / scenario), store)
    return store


def context(store, viewer, since_tick=3, **kw):
    return compile_context(
        store, viewer, since_tick, role_card=rf.role_card(viewer, 6), templates=rf.TEMPLATES, **kw
    )


def test_context_after_a_correction_matches_the_snapshot():
    # A3 was told "day 4" by A2 and has just learned A2 cannot be trusted
    store = played(MemoryStore())
    (stale,) = store.beliefs("A3", status="stale")
    store.add_node(Action(id="X1", owner="A3", type="water", target="F3", status="committed"))
    store.add_edge(Edge(kind="DERIVED_FROM", src="X1", dst=stale.id))
    assert_snapshot("a3_after_exposure", context(store, "A3"))


def test_context_before_any_correction_matches_the_snapshot():
    store = played(MemoryStore())
    assert_snapshot("a1_quiet_turn", context(store, "A1", since_tick=1))


def test_a_corrected_belief_appears_as_a_tombstone_and_not_as_a_current_belief():
    store = played(MemoryStore())
    text = context(store, "A3")
    (stale,) = store.beliefs("A3", status="stale")
    changed, _, beliefs = text.partition("## Beliefs")
    assert f"[{stale.id} STALE]" in changed
    assert stale.id not in beliefs  # it is never offered again as something to believe


def test_a_commitment_that_depends_on_a_corrected_belief_is_flagged():
    store = played(MemoryStore())
    (stale,) = store.beliefs("A3", status="stale")
    store.add_node(Action(id="X1", owner="A3", type="water", target="F3", status="committed"))
    store.add_edge(Edge(kind="DERIVED_FROM", src="X1", dst=stale.id))
    assert f"! depends on {stale.id}, which is stale" in context(store, "A3")


def test_an_agent_is_never_shown_another_agents_beliefs():
    store = played(MemoryStore())
    mine = {b.id for b in store.beliefs("A1")}
    others = {b.id for b in store.beliefs("A4")} - mine
    text = context(store, "A1", since_tick=0)
    assert all(f"[{b} " not in text for b in others)


@pytest.mark.parametrize("budget", [400, 800, 2000])
def test_the_context_stays_within_the_budget(budget):
    store = played(MemoryStore())
    text = context(store, "A3", since_tick=0, budget=budget)
    assert estimate_tokens(text) <= budget


def test_a_tight_budget_drops_the_least_relevant_beliefs_and_says_so():
    store = played(MemoryStore())
    full = context(store, "A3", since_tick=0, budget=4000)
    tight = context(store, "A3", since_tick=0, budget=330)
    assert "not shown" in tight and "not shown" not in full
    assert "## Changed since last turn" in tight  # corrections are never dropped first


@pytest.mark.parametrize("store_factory", STORES)
@pytest.mark.parametrize("scenario", ["bias_chain.json", "false_alarm.json"])
def test_every_store_compiles_exactly_the_same_context(store_factory, scenario):
    reference, other = MemoryStore(), store_factory()
    try:
        played(reference, scenario)
        played(other, scenario)
        for agent in range(6):
            viewer = f"A{agent}"
            for since in (0, 2):
                assert context(other, viewer, since) == context(reference, viewer, since)
    finally:
        other.close()
