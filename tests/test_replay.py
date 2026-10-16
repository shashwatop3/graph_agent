"""Recording a game as JSON and writing the viewer page."""

import json
import re
from pathlib import Path

from fake_agent import honest_agent
from graph_agent.harness.backend import GraphBackend
from graph_agent.harness.baselines import SharedLogBackend
from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall
from graph_agent.harness.replay import TEMPLATE, record_replay, write_viewer
from graph_agent.sim.scenario import load_scenario
from graph_agent.stores.memory import MemoryStore

SCENARIO = {
    **load_scenario(Path(__file__).parent / "scenarios" / "live_ring.json"),
    "evidence": "public",
}


def record(backend=None, client=None):
    return record_replay(
        SCENARIO, backend or GraphBackend(MemoryStore()), client or honest_agent(6)
    )


def test_a_replay_describes_the_ring_the_imposters_and_every_day():
    replay = record()
    assert replay["n_agents"] == 6 and len(replay["fields"]) == 6
    assert replay["imposters"] == {"2": "subtle_bias"}
    assert [d["day"] for d in replay["days"]] == list(range(len(replay["days"])))
    assert replay["system"] == "graph"
    assert json.loads(json.dumps(replay)) == replay  # plain JSON all the way down


def test_fires_messages_and_corrections_are_on_the_day_they_happened():
    replay = record()
    first = replay["days"][0]
    assert [e["field"] for e in first["ignited"]] == [0]  # the starting fire is on day 0
    assert any(m["altered_by"] == [2] for m in first["messages"])  # A2's shifted claim, day 0
    (exposure,) = [e for d in replay["days"] for e in d["exposures"]]
    assert (exposure["viewer"], exposure["agent"]) == (3, 2)
    assert exposure["changes"][0]["status"] == "stale"
    assert "fire reaches F0 on day 1" in exposure["changes"][0]["text"]  # in words, not an id


def test_every_message_in_the_game_is_in_the_replay_once():
    replay = record()
    assert sum(len(d["messages"]) for d in replay["days"]) == replay["score"]["messages"]


def test_a_baseline_records_a_game_with_no_corrections():
    from fake_baseline_agent import log_reader

    replay = record(SharedLogBackend(), log_reader(6))
    assert replay["system"] == "B1-shared-log"
    assert all(d["exposures"] == [] for d in replay["days"])
    assert replay["score"]["propagation_precision"] is None


def test_a_shortcut_link_an_agent_builds_is_recorded_on_its_day():
    def policy(system, messages, tools):
        if messages[0]["content"].startswith("## Role") and "You are A3" in messages[0]["content"]:
            day = int(re.search(r"It is day (\d+)", messages[0]["content"]).group(1))
            if day == 1 and not any(m["role"] == "tool" for m in messages):
                return ModelReply(
                    tool_calls=[ToolCall("act", {"type": "link", "target": "A5"}, "l")]
                )
        return ModelReply(text="done")

    replay = record(client=ScriptedModel(policy))
    added = {d["day"]: d["links_added"] for d in replay["days"] if d["links_added"]}
    assert added == {1: [[3, 5]]}


def test_the_viewer_page_embeds_the_replay_and_nothing_is_left_to_fill_in(tmp_path):
    replay = record()
    page = write_viewer(replay, tmp_path / "replay.html").read_text()
    assert "__REPLAY__" not in page
    embedded = re.search(r'<script id="replay" type="application/json">(.*?)</script>', page, re.S)
    assert json.loads(embedded.group(1)) == replay


def test_text_that_could_close_the_script_tag_is_escaped(tmp_path):
    replay = record()
    replay["system"] = "</script><b>x"
    page = write_viewer(replay, tmp_path / "r.html").read_text()
    assert page.count("</script>") == 2  # the replay's own and the page's code, never a third


def test_the_template_exists_and_has_a_title():
    text = TEMPLATE.read_text()
    assert "<title>Ring Fire Replay</title>" in text and "__REPLAY__" in text
