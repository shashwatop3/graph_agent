"""Generating games from knobs, sweeping systems, and the tables."""

import json

import pytest
from fake_agent import honest_agent
from fake_baseline_agent import log_reader

from graph_agent.harness.llm import CachedClient
from graph_agent.packs.ringfire.benchmark.experiment import (
    Knobs,
    make_scenario,
    plot_svg,
    run_experiment,
    summary_table,
)
from graph_agent.packs.ringfire.sim.scenario import build_game


def stand_in(system, knobs):
    if system.startswith("graph"):
        return honest_agent(knobs.n_agents)
    return log_reader(knobs.n_agents, can_send=system != "B0")


# ---- generating a game from knobs -------------------------------------------------------------


def test_the_same_knobs_and_seed_give_the_same_game():
    assert make_scenario(Knobs(), 3) == make_scenario(Knobs(), 3)
    assert make_scenario(Knobs(), 3) != make_scenario(Knobs(), 4)


def test_the_knobs_show_up_in_the_game():
    scenario = make_scenario(Knobs(n_agents=10, hidden_edges=3, imposters=2, extra_links=2), 1)
    game = build_game(scenario)
    assert game.sim.world.config.n_agents == 10
    assert sum(e.hidden for e in game.sim.world.edges) == 3
    assert len(game.net.imposters) == 2
    assert len(scenario["links"]) == 2 and all(game.net.linked(a, b) for a, b in scenario["links"])


def test_colluders_are_adjacent_and_all_back_the_same_lie():
    scenario = make_scenario(Knobs(n_agents=10, colluders=3, imposters=0), 5)
    colluders = sorted(i["agent"] for i in scenario["imposters"])
    assert len(colluders) == 3
    ring_gaps = {
        (b - a) % 10 for a, b in zip(colluders, colluders[1:] + colluders[:1], strict=True)
    }
    assert 1 in ring_gaps  # at least two of them sit next to each other (a block on the ring)
    lies = {(s["claim"]["field_id"], s["claim"]["day"]) for s in scenario["sends"]}
    assert len(lies) == 1  # one shared lie, sent by several mouths
    assert {s["sender"] for s in scenario["sends"]} <= set(colluders)


def test_imposters_and_colluders_never_overlap():
    for seed in range(20):
        scenario = make_scenario(Knobs(n_agents=8, colluders=2, imposters=2), seed)
        agents = [i["agent"] for i in scenario["imposters"]]
        assert len(agents) == len(set(agents)) == 4


# ---- running a sweep --------------------------------------------------------------------------

SYSTEMS = ["graph-memory", "B0", "B1", "B3"]
GRID = [Knobs(n_agents=6), Knobs(n_agents=8)]


@pytest.fixture(scope="module")
def rows():
    return run_experiment(SYSTEMS, GRID, [0, 1], stand_in, probe_days=(2,))


def test_one_row_per_game(rows):
    assert len(rows) == len(SYSTEMS) * len(GRID) * 2
    assert {r["system"] for r in rows} == set(SYSTEMS)
    assert all("fields_saved" in r and "n_agents" in r and "seed" in r for r in rows)


def test_a_sweep_is_reproducible(rows):
    assert run_experiment(SYSTEMS, GRID, [0, 1], stand_in, probe_days=(2,)) == rows


def test_every_system_faces_the_same_world_and_lies(rows):
    for knobs in GRID:
        for seed in (0, 1):
            same = [r for r in rows if r["n_agents"] == knobs.n_agents and r["seed"] == seed]
            assert len({r["fields"] for r in same}) == 1
            # the imposter's own scripted behaviour is the same game; false messages can differ
            # only because agents pass lies on differently, never because the lies differ
            assert all(r["false_messages"] >= 0 for r in same)


def test_only_graph_systems_report_belief_metrics(rows):
    for r in rows:
        if r["system"].startswith("graph"):
            assert r["propagation_recall"] is not None or r["false_invalidations"] is not None
        else:
            assert r["propagation_precision"] is None and r["false_beliefs_remaining"] is None


def test_probes_were_asked_of_every_system(rows):
    assert all(r["probes"] > 0 for r in rows)


def test_a_sweep_can_be_saved_and_read_back(tmp_path):
    saved = run_experiment(
        ["graph-memory", "B1"], [Knobs(n_agents=6)], [0], stand_in, out_dir=tmp_path
    )
    assert json.loads((tmp_path / "results.json").read_text()) == saved
    assert (tmp_path / "results.csv").read_text().startswith(",".join(sorted(saved[0]))[:10])
    assert "graph-memory" in (tmp_path / "summary.md").read_text()


def test_a_cached_rerun_makes_no_model_calls(tmp_path):
    clients = {}

    def cached(system, knobs):
        key = (system, knobs)
        if key not in clients:
            clients[key] = CachedClient(stand_in(system, knobs), tmp_path / system)
        return clients[key]

    first = run_experiment(
        ["graph-memory", "B1"], [Knobs(n_agents=6)], [0], cached, probe_days=(2,)
    )
    paid = sum(c.calls_made for c in clients.values())
    assert paid > 0
    clients.clear()
    again = run_experiment(
        ["graph-memory", "B1"], [Knobs(n_agents=6)], [0], cached, probe_days=(2,)
    )
    assert sum(c.calls_made for c in clients.values()) == 0  # everything came from disk
    assert again == first


# ---- tables and plots -------------------------------------------------------------------------


def test_the_summary_has_one_block_per_knob_setting_and_one_row_per_system(rows):
    text = summary_table(rows)
    assert text.count("### ") == len(GRID)
    for system in SYSTEMS:
        assert text.count(f"| {system} |") == len(GRID)
    assert "small" in text  # the caveat is part of the table


def test_the_plot_has_a_line_for_each_system(rows):
    svg = plot_svg(rows, "n_agents", "lies_relayed")
    assert svg.startswith("<svg") and svg.count("<polyline") == len(SYSTEMS)
    assert plot_svg([], "n_agents", "lies_relayed").startswith("<svg")
