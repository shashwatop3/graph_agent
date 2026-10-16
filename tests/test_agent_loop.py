"""The agent loop, the model cache and a whole game with stand-in agents (no provider, no cost)."""

from pathlib import Path

import pytest

from fake_agent import honest_agent
from graph_agent.adapters import ringfire as rf
from graph_agent.core.ids import Ids
from graph_agent.core.tools import TOOL_NAMES, Toolbox
from graph_agent.harness.agent import call_tool, run_turn, tool_schemas
from graph_agent.harness.backend import GraphBackend
from graph_agent.harness.game import run_game
from graph_agent.harness.llm import CachedClient, ModelReply, ScriptedModel, ToolCall
from graph_agent.sim.scenario import load_scenario
from graph_agent.stores.memory import MemoryStore
from stores_param import STORES

SCENARIO = load_scenario(Path(__file__).parent / "scenarios" / "live_ring.json")


# ---- tool schemas -----------------------------------------------------------------------------


def test_every_tool_has_a_schema_with_its_required_arguments():
    schemas = {s["name"]: s for s in tool_schemas(box())}
    assert list(schemas) == list(TOOL_NAMES)
    assert schemas["send"]["parameters"]["required"] == ["to", "belief_id"]
    assert schemas["assert_belief"]["parameters"]["required"] == [
        "subject",
        "predicate",
        "value",
        "depends_on",
    ]
    assert schemas["recall"]["parameters"]["required"] == []
    assert all(s["description"] for s in schemas.values())


# ---- one turn ---------------------------------------------------------------------------------


def box():
    store = MemoryStore()
    rf.setup_map(store, 3, [(f, f) for f in range(3)], [(f, (f + 1) % 3, 1) for f in range(3)])
    return Toolbox(store, "A1", rf.PREDICATES, rf.TEMPLATES, Ids())


def test_a_turn_runs_the_tool_calls_in_order_and_ends_when_the_model_stops():
    seen = []

    def policy(system, messages, tools):
        seen.append([m["role"] for m in messages])
        if len(seen) == 1:
            return ModelReply(
                tool_calls=[
                    ToolCall("recall", {}, "1"),
                    ToolCall("traverse", {"entity": "F1"}, "2"),
                ]
            )
        return ModelReply(text="all done")

    result = run_turn(ScriptedModel(policy), box(), "context")
    assert [name for name, _, _ in result.calls] == ["recall", "traverse"]
    assert result.final_text == "all done" and result.steps == 2
    assert seen[1] == ["user", "assistant", "tool", "tool"]  # the model saw both results


def test_a_turn_is_cut_off_after_max_steps():
    forever = ScriptedModel(lambda s, m, t: ModelReply(tool_calls=[ToolCall("recall", {}, "x")]))
    assert run_turn(forever, box(), "context", max_steps=3).steps == 3


def test_a_bad_tool_call_comes_back_as_an_error_the_model_can_read():
    b = box()
    assert call_tool(b, "dance", {}).startswith("error: unknown tool")
    assert "bad arguments" in call_tool(b, "send", {"nonsense": 1})
    assert call_tool(b, "explain", {"belief_id": "nope"}).startswith("error:")


# ---- the cache --------------------------------------------------------------------------------


def counting_model():
    calls = []

    def policy(system, messages, tools):
        calls.append(messages)
        return ModelReply(text=f"answer {len(calls)}", tokens_in=100, tokens_out=10)

    return ScriptedModel(policy, model="m1"), calls


def test_a_repeated_request_is_answered_from_disk_and_costs_nothing(tmp_path):
    model, calls = counting_model()
    client = CachedClient(model, tmp_path)
    first = client.complete("sys", [{"role": "user", "content": "hi"}], [])
    again = client.complete("sys", [{"role": "user", "content": "hi"}], [])
    assert first == again and len(calls) == 1
    assert (client.calls_made, client.cache_hits) == (1, 1)
    assert (client.tokens_in, client.tokens_out) == (100, 10)  # only the real call is counted


def test_the_cache_survives_a_new_client_and_separates_requests_and_models(tmp_path):
    model, calls = counting_model()
    CachedClient(model, tmp_path).complete("sys", [{"role": "user", "content": "hi"}], [])
    fresh = CachedClient(model, tmp_path)
    fresh.complete("sys", [{"role": "user", "content": "hi"}], [])
    assert fresh.calls_made == 0  # a different process or run still hits
    fresh.complete("sys", [{"role": "user", "content": "other"}], [])
    assert fresh.calls_made == 1  # a different request does not
    other_model = ScriptedModel(lambda s, m, t: ModelReply(text="x"), model="m2")
    other = CachedClient(other_model, tmp_path)
    assert other.complete("sys", [{"role": "user", "content": "hi"}], []).text == "x"


def test_tool_calls_survive_the_cache(tmp_path):
    reply = ModelReply(tool_calls=[ToolCall("send", {"to": "A2", "belief_id": "B1"}, "c1")])
    client = CachedClient(ScriptedModel(lambda s, m, t: reply), tmp_path)
    client.complete("s", [], [])
    assert (
        CachedClient(ScriptedModel(lambda s, m, t: 1 / 0), tmp_path).complete("s", [], []) == reply
    )


# ---- a whole game -----------------------------------------------------------------------------


def summary(result):
    return {
        "exposures": [(e.viewer, e.agent, e.day, len(e.changes)) for e in result.exposures],
        "turns": [(d, a, [(n, args) for n, args, _ in t.calls]) for d, a, t in result.turns],
        "saved": result.fields_saved,
        "sent": [(m.sender, m.receiver, m.claim, m.altered_by) for m in result.game.net.log],
    }


def play(store, client=None):
    return run_game(SCENARIO, GraphBackend(store), client or honest_agent(6))


def test_a_game_with_stand_in_agents_runs_to_the_end_and_catches_the_imposter():
    result = play(MemoryStore())
    assert result.game.finished
    # agent 2 shifts every claim it passes on, so the agents it told stop trusting it
    first = result.exposures[0]
    assert (first.viewer, first.agent) == ("A3", "A2")  # A3 hears A2's shifted claim first
    assert any(m.altered_by == (2,) for m in result.game.net.log)
    assert all(e.changes for e in result.exposures)  # each exposure invalidated something
    assert result.tokens_in > 0


def test_the_lie_is_caught_once_and_goes_no_further():
    result = play(MemoryStore())
    # A2 shifts claims, A3 catches the first one the day it arrives, and nothing else is blamed
    assert [(e.viewer, e.agent, e.day) for e in result.exposures] == [("A3", "A2", 0)]
    assert {f"A{a}" for a in result.game.net.imposters} == {"A2"}


def test_after_distrusting_an_agent_what_it_sends_is_seen_but_never_believed():
    store = MemoryStore()
    result = play(store)
    later = [m for m in result.game.net.log if m.receiver == 3 and 2 in m.route and m.day > 0]
    assert later  # A2 kept sending to A3 after A3 stopped trusting it
    for belief in store.beliefs("A3", status="active"):
        routes = store.support_routes("A3", belief.id)
        assert all("A2" not in route for route in routes), belief
    inbox = {o.id for o in store.observations("A3", since_tick=1)}
    assert len(inbox) >= len(later)  # but it is all in the inbox, with its route


def test_the_imposter_never_calls_the_model():
    result = play(MemoryStore())
    assert "A2" not in {agent for _, agent, _ in result.turns}


def test_agents_water_when_fire_is_due_and_never_two_days_running():
    result = play(MemoryStore())
    watered = {
        (day, agent)
        for day, agent, turn in result.turns
        for name, args, output in turn.calls
        if name == "act" and output.endswith("you will water your fields today")
    }
    assert watered  # somebody watered
    for day, agent in watered:
        assert (day - 1, agent) not in watered


def test_the_same_game_twice_is_identical():
    assert summary(play(MemoryStore())) == summary(play(MemoryStore()))


def test_a_cached_rerun_makes_no_model_calls_and_changes_nothing(tmp_path):
    first_client = CachedClient(honest_agent(6), tmp_path)
    first = play(MemoryStore(), first_client)
    assert first_client.calls_made > 0 and first_client.tokens_in > 0

    second_client = CachedClient(ScriptedModel(lambda s, m, t: 1 / 0), tmp_path)  # must not be used
    second = play(MemoryStore(), second_client)
    assert second_client.calls_made == 0 and second_client.cache_hits == first_client.calls_made
    assert summary(second) == summary(first)


@pytest.mark.parametrize("store_factory", STORES)
def test_every_store_plays_the_identical_game(store_factory):
    store = store_factory()
    try:
        assert summary(play(store)) == summary(play(MemoryStore()))
    finally:
        store.close()
