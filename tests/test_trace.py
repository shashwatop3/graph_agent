"""The run log: a game with stand-in agents writes the events needed to debug it afterwards."""

import json

from fake_agent import honest_agent
from graph_agent.harness.experiment import Knobs, run_experiment

KNOBS = Knobs(n_agents=6, imposters=1, behaviour="false_alarm")


def run_logged(tmp_path, system="graph-memory"):
    run_experiment(
        [system],
        [KNOBS],
        [0],
        lambda *_: honest_agent(6),
        probe_days=(2,),
        out_dir=tmp_path / "out",
        log_dir=tmp_path / "logs",
    )
    (log,) = (tmp_path / "logs").glob("*.jsonl")
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_a_logged_game_records_every_step_of_the_story(tmp_path):
    events = run_logged(tmp_path)
    kinds = {e["kind"] for e in events}
    assert {"game_start", "day_start", "turn_start", "model_call", "tool_result"} <= kinds
    assert "message" in kinds
    assert {"turn_end", "day_end", "probe", "probe_scored", "beliefs", "score"} <= kinds
    assert events[0]["kind"] == "game_start" and events[-1]["kind"] == "score"


def test_events_carry_the_day_and_agent_they_belong_to(tmp_path):
    events = run_logged(tmp_path)
    start = next(e for e in events if e["kind"] == "turn_start")
    assert start["agent"].startswith("A") and "day" in start and start["context"]
    call = next(e for e in events if e["kind"] == "model_call")
    assert call["agent"] and call["step"] >= 1 and "tokens_in" in call


def test_a_baseline_logs_too_but_has_no_belief_snapshot(tmp_path):
    kinds = {e["kind"] for e in run_logged(tmp_path, "B1")}
    assert "turn_end" in kinds and "beliefs" not in kinds


def test_results_are_saved_as_each_game_finishes(tmp_path):
    run_logged(tmp_path)
    assert (tmp_path / "out" / "results.json").exists()
