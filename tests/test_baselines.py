"""The comparison systems B0 to B3, and the checks that the comparison is like for like."""

from pathlib import Path

import pytest

from fake_agent import honest_agent
from fake_baseline_agent import log_reader
from graph_agent.core.compiler import estimate_tokens
from graph_agent.harness.agent import tool_schemas
from graph_agent.harness.backend import GraphBackend
from graph_agent.harness.baselines import (
    BASELINES,
    CHECKLIST,
    IsolatedBackend,
    PromptOnlyBackend,
    SharedLogBackend,
    VectorMemoryBackend,
    most_similar,
)
from graph_agent.harness.game import run_game
from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.sim.scenario import load_scenario
from graph_agent.stores.memory import MemoryStore

SCENARIO = load_scenario(Path(__file__).parent / "scenarios" / "live_ring.json")


def idle() -> ScriptedModel:
    """A model that never does anything: whatever differs between runs is not the agents."""
    return ScriptedModel(lambda s, m, t: ModelReply(text="nothing to do", tokens_in=1))


def play(backend, client=None, scenario=SCENARIO, **kw):
    return run_game(
        scenario, backend, client or log_reader(6, can_send=backend.name != "B0-isolated"), **kw
    )


# ---- similarity search ------------------------------------------------------------------------


def test_most_similar_finds_the_matching_line_and_prefers_the_newer_on_ties():
    docs = ["rain over the hills", "fire reaches F3 on day 4", "fire reaches F3 on day 4", "snow"]
    assert most_similar(docs, "fire F3", k=2) == [2, 1]
    assert most_similar(docs, "snow", k=1) == [3]
    assert most_similar([], "anything", k=3) == []


# ---- each baseline ----------------------------------------------------------------------------


@pytest.mark.parametrize("name", BASELINES)
def test_every_baseline_plays_a_whole_game(name):
    result = play(BASELINES[name]())
    assert result.game.finished
    assert result.tokens_in > 0 and result.turns
    assert result.exposures == []  # baselines never distrust anyone on the agent's behalf


def test_b0_agents_are_isolated_and_can_only_act():
    backend = IsolatedBackend()
    result = play(backend)
    box = backend.toolbox(0, None, None)
    assert [s["name"] for s in tool_schemas(box)] == ["act"]
    assert all(name == "act" for _, _, t in result.turns for name, _, _ in t.calls)
    context = backend.context(0, 3, 4000)
    assert "told" not in context and "PUBLISHED" in context  # evidence, but no messages


def test_b1_shows_everyone_everything_in_one_log():
    backend = SharedLogBackend()
    play(backend)
    context = backend.context(0, 3, 4000)
    assert "told A1" in context or "told A5" in context
    assert "A2 told" in context  # a conversation between other agents is visible too
    assert context.index("## Role") < context.index("## Map") < context.index("## Shared log")


def test_b3_is_b1_plus_a_strong_prompt():
    b1, b3 = SharedLogBackend(), PromptOnlyBackend()
    play(b1), play(b3)
    assert CHECKLIST in b3.context(0, 3, 4000) and CHECKLIST not in b1.context(0, 3, 4000)
    assert b3.lines == b1.lines  # the same stream: only the prompt differs


def test_b2_shows_relevant_and_recent_lines_not_the_whole_log():
    backend = VectorMemoryBackend()
    play(backend)
    context = backend.context(3, 3, 700)
    shown = [line for line in context.splitlines() if line.startswith("day ")]
    assert 0 < len(shown) < len(backend.lines)
    assert backend.lines[-1] in context  # the newest line is always there
    assert "not shown" in context


# ---- fairness ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", BASELINES)
@pytest.mark.parametrize("budget", [500, 1200])
def test_every_baseline_respects_the_same_token_budget(name, budget):
    backend = BASELINES[name]()
    play(backend)
    for agent in range(6):
        assert estimate_tokens(backend.context(agent, 5, budget)) <= budget


def test_every_baseline_is_told_the_same_map_the_graph_agents_can_query():
    backend = SharedLogBackend()
    play(backend)
    context = backend.context(0, 1, 4000)
    for field in range(6):
        assert f"F{field} -> F{(field + 1) % 6}: fire takes 1 day(s)" in context


def test_the_imposters_lies_reach_the_baselines_exactly_as_they_reach_the_graph_setup():
    graph, log = GraphBackend(MemoryStore()), SharedLogBackend()
    graph_game = play(graph, honest_agent(6)).game
    log_game = play(log).game
    shifted = [m for m in log_game.net.log if m.altered_by]
    assert shifted and all(m.altered_by == (2,) for m in shifted)  # all traceable to A2
    assert any(m.altered_by for m in graph_game.net.log)


@pytest.mark.parametrize("name", BASELINES)
def test_when_nobody_acts_every_system_burns_the_same_fields(name):
    """The simulator is identical under every system: with idle agents the fire is the same."""
    reference = run_game(SCENARIO, GraphBackend(MemoryStore()), idle())
    result = run_game(SCENARIO, BASELINES[name](), idle())
    assert result.fields_saved == reference.fields_saved
    assert [f.ignited_on for f in result.game.sim.fields] == [
        f.ignited_on for f in reference.game.sim.fields
    ]
