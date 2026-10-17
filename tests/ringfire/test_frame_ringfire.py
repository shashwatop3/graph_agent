"""Ring Fire on the frame gives exactly the game of the original loop (harness/game.py with
GraphBackend): the same log, event for event, and the same score, across the game's variants.

The stand-in model only sees the text it is sent, so identical logs mean the frame showed every
agent the same context and the same tools, and the graph changed in the same way.
"""

import json
from pathlib import Path

import pytest
from fake_agent import honest_agent

from graph_agent.frame.spec import TeamSpec, load_team, save_team
from graph_agent.harness.trace import Trace
from graph_agent.packs.ringfire.benchmark.backend import GraphBackend
from graph_agent.packs.ringfire.benchmark.experiment import Knobs, make_scenario
from graph_agent.packs.ringfire.benchmark.game import run_game
from graph_agent.packs.ringfire.benchmark.scoring import Probe, make_probe_hook, score_game
from graph_agent.packs.ringfire.pack import run_frame_game, team_for
from graph_agent.stores.memory import MemoryStore

VARIANTS = {
    "false alarm": Knobs(n_agents=8, imposters=2, behaviour="false_alarm", extra_links=1),
    "colluders, hidden paths": Knobs(
        n_agents=10,
        fields_per_agent=2,
        hidden_edges=2,
        imposters=1,
        colluders=2,
        behaviour="false_alarm",
        extra_links=2,
    ),
    "subtle bias": Knobs(n_agents=8, imposters=2, behaviour="subtle_bias"),
    "hide fire, public evidence": Knobs(
        n_agents=6, imposters=1, behaviour="hide_fire", evidence="public"
    ),
    "saboteurs, long game": Knobs(
        n_agents=8,
        imposters=2,
        behaviour="saboteur",
        horizon=12,
        regrow_days=2,
        random_fire_chance=0.2,
        water_cooldown=2,
        waste_penalty=0.5,
    ),
}


def events(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        row.pop("t")
    return rows


def play_both(tmp_path: Path, knobs: Knobs, seed: int, quorum: int | None):
    scenario = make_scenario(knobs, seed)
    results = []
    for which in ("old", "frame"):
        trace = Trace(tmp_path / f"{which}.jsonl")
        client = honest_agent(knobs.n_agents)
        probes: list[Probe] = []
        hook = make_probe_hook(client, probes, 4000, {2, 4}, trace)
        if which == "old":
            backend = GraphBackend(MemoryStore(), name="graph-memory", warn_quorum=quorum)
            result = run_game(scenario, backend, client, after_day=hook, trace=trace)
            view = backend
        else:
            result, view = run_frame_game(
                scenario,
                MemoryStore(),
                client,
                after_day=hook,
                trace=trace,
                quorum=quorum,
                system="graph-memory",
            )
        trace.close()
        results.append((score_game(result, view, probes), events(tmp_path / f"{which}.jsonl")))
    return results


@pytest.mark.parametrize("name", list(VARIANTS))
@pytest.mark.parametrize("quorum", [None, 1])
def test_the_frame_plays_the_same_game(tmp_path, name, quorum):
    (old_score, old_log), (new_score, new_log) = play_both(tmp_path, VARIANTS[name], 3, quorum)
    assert new_log == old_log
    assert new_score == old_score


def test_the_game_is_a_team_file_the_canvas_can_show(tmp_path):
    scenario = make_scenario(VARIANTS["false alarm"], 1)
    team = team_for(scenario, quorum=1)
    save_team(team, tmp_path / "team.json")
    loaded = load_team(tmp_path / "team.json")
    assert isinstance(loaded, TeamSpec) and loaded == team
    types = {n.id: n.type for n in team.nodes}
    imposters = {i["agent"] for i in scenario["imposters"]}
    assert types["world"] == "ringfire.world" and types["checker"] == "checker"
    assert types["warner"] == "warner"
    assert all(types[f"A{a}"] == ("scripted" if a in imposters else "agent") for a in range(8))
    owned = {link.dst for link in team.links if link.kind == "owns"}
    assert owned == {f"F{f}" for f in range(8)}
    # and a game played from the saved file is the same game
    a, _ = run_frame_game(scenario, MemoryStore(), honest_agent(8), team=loaded)
    b, _ = run_frame_game(scenario, MemoryStore(), honest_agent(8), quorum=1)
    assert a.fields_saved == b.fields_saved and len(a.exposures) == len(b.exposures)


def test_waking_only_on_news_saves_turns_and_still_waters():
    knobs = VARIANTS["false alarm"]
    scenario = make_scenario(knobs, 2)
    lockstep, _ = run_frame_game(scenario, MemoryStore(), honest_agent(8))
    woken, view = run_frame_game(scenario, MemoryStore(), honest_agent(8), wake=True)
    assert len(woken.turns) < len(lockstep.turns)
    assert woken.fields_saved >= lockstep.fields_saved - 1
    assert view.exposures  # the liars are still caught


def test_the_rerouter_links_around_a_liar_without_being_asked():
    scenario = make_scenario(VARIANTS["false alarm"], 1)
    result, view = run_frame_game(scenario, MemoryStore(), honest_agent(8), rerouter=True)
    plain, _ = run_frame_game(scenario, MemoryStore(), honest_agent(8))
    added = result.game.net.links - plain.game.net.links
    assert added
    done = [e for e in view.runtime.log.events if e.kind == "action" and e.data["tool"] == "link"]
    assert {frozenset(int(x[1:]) for x in e.data["arguments"].values()) for e in done} >= added
    for event in done:  # each link starts at an honest agent and skips only whom it distrusts
        viewer = event.data["arguments"]["from"]
        assert int(viewer[1:]) not in result.game.net.imposters
        assert view.runtime.distrusted(viewer)


@pytest.mark.integration
def test_the_frame_on_falkordb_plays_the_same_game():
    from graph_agent.stores.falkor import FalkorStore

    scenario = make_scenario(VARIANTS["false alarm"], 3)
    memory, memory_view = run_frame_game(scenario, MemoryStore(), honest_agent(8), quorum=1)
    store = FalkorStore()
    try:
        falkor, falkor_view = run_frame_game(scenario, store, honest_agent(8), quorum=1)
        assert score_game(falkor, falkor_view) == score_game(memory, memory_view)
    finally:
        store.close()
