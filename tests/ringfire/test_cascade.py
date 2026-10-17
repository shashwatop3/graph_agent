"""The Cascade viewer's data: run logs turned into days, messages, turns and belief chains."""

import json

import pytest
from fake_agent import honest_agent

from graph_agent.packs.ringfire.benchmark.cascade import (
    DATA_TAG,
    TEMPLATE,
    belief_chains,
    cascade_data,
    read_log,
    run_view,
    write_viewer,
)
from graph_agent.packs.ringfire.benchmark.experiment import Knobs, run_experiment

KNOBS = Knobs(n_agents=6, imposters=1, behaviour="false_alarm")


def logged(tmp_path, systems, seeds=(0,)):
    run_experiment(
        list(systems),
        [KNOBS],
        list(seeds),
        lambda *_: honest_agent(6),
        probe_days=(2,),
        log_dir=tmp_path,
    )
    return {p.name.split("_")[0] + "_" + p.stem.split("_")[-1]: p for p in tmp_path.glob("*.jsonl")}


def test_one_game_played_by_two_systems_becomes_one_comparison(tmp_path):
    logs = logged(tmp_path, ["graph-memory", "B1"])
    data = cascade_data({"graph": logs["graph-memory_s0"], "chat": logs["B1_s0"]})
    assert list(data["runs"]) == ["graph", "chat"]
    assert data["scenario"]["n_agents"] == 6 and len(data["scenario"]["imposters"]) == 1
    for run in data["runs"].values():
        assert [d["day"] for d in run["days"]] == list(range(len(run["days"])))
        assert run["turns"] and run["score"]
    assert json.loads(json.dumps(data)) == data  # plain JSON all the way down


def test_logs_of_different_games_are_refused(tmp_path):
    logs = logged(tmp_path, ["graph-memory"], seeds=(0, 1))
    with pytest.raises(ValueError, match="different game"):
        cascade_data({"a": logs["graph-memory_s0"], "b": logs["graph-memory_s1"]})


def test_the_imposters_lies_are_marked_and_only_graph_runs_have_beliefs(tmp_path):
    logs = logged(tmp_path, ["graph-memory", "B1"])
    graph, chat = (run_view(read_log(logs[k])) for k in ("graph-memory_s0", "B1_s0"))
    assert any(m["altered"] for m in graph["messages"])
    assert graph["beliefs"] and chat["beliefs"] == {}


def test_a_new_log_records_when_each_belief_was_made_and_what_it_came_from(tmp_path):
    logs = logged(tmp_path, ["graph-memory"])
    snapshot = [e for e in read_log(logs["graph-memory_s0"]) if e["kind"] == "beliefs"]
    assert snapshot and all("created_tick" in e and "sources" in e for e in snapshot)


# ---- belief chains, on a hand-written log ------------------------------------------------------
# A1 lies to A2 about F9; A0 passes the same lie on through A1. A2 sees the truth, stops trusting
# A1 and then A0, so the lie loses both routes and goes stale. A2 also works out F9's arrival from
# what it saw and sends that to A3; A3 is an imposter that passes it on to A4.


def message(day, sender, receiver, route, claim_day, altered=()):
    return {
        "kind": "message", "day": day, "sender": sender, "receiver": receiver, "route": route,
        "field": 9, "claim_day": claim_day, "altered_by": list(altered), "held": False,
    }  # fmt: skip


def belief(agent, bid, value, origin, routes, status="active", **new_fields):
    return {
        "kind": "beliefs", "agent": agent, "belief": bid, "subject": "F9", "value": value,
        "origin": origin, "status": status, "claim_true": value == 1, "routes": routes,
        **new_fields,
    }  # fmt: skip


def story(new_format):
    extra = (
        (lambda tick, src: {"created_tick": tick, "sources": src})
        if new_format
        else (lambda tick, src: {})
    )
    return [
        message(1, 1, 2, [1], 5, altered=[1]),
        message(1, 1, 2, [0, 1], 5, altered=[0]),
        {"kind": "exposure", "day": 1, "viewer": "A2", "distrusted": "A1", "reason": "lied",
         "changes": []},
        {"kind": "exposure", "day": 2, "viewer": "A2", "distrusted": "A0", "reason": "lied too",
         "changes": [["B1", "active", "stale", 1]]},
        {"kind": "tool_result", "day": 2, "agent": "A2", "tool": "assert_belief",
         "arguments": {"subject": "F9", "value": 1, "depends_on": ["B2"]}, "result": "recorded B3",
         "error": False},
        {"kind": "tool_result", "day": 2, "agent": "A2", "tool": "send",
         "arguments": {"to": "A3", "belief_id": "B3"}, "result": "sent to A3", "error": False},
        message(2, 2, 3, [2], 1),
        {"kind": "imposter_relay", "day": 3, "imposter": 3, "to": 4, "field": 9, "claim_day": 1,
         "delivered": True},
        message(3, 3, 4, [2, 3], 1),
        belief("A2", "B1", 5, "told", [["A0", "A1"], ["A1"]], "stale", **extra(1, [])),
        belief("A2", "B2", 1, "observed", [[]], **extra(1, [])),
        belief("A2", "B3", 1, "derived", [], **extra(2, ["B2"])),
        belief("A3", "B4", 1, "told", [["A2"]], **extra(2, [])),
        belief("A4", "B5", 1, "told", [["A2", "A3"]], **extra(3, [])),
    ]  # fmt: skip


@pytest.mark.parametrize("new_format", [True, False], ids=["snapshot", "older log"])
def test_a_belief_chain_tells_where_a_belief_came_from_and_where_it_went(new_format):
    chains = belief_chains(story(new_format))
    lie, seen, worked_out = chains["2"]
    assert lie["routes"] == [[0, 1], [1]] and lie["born"] == 1
    assert [(c["day"], c["agent"]) for c in lie["cuts"]] == [(1, 1), (2, 0)]
    assert lie["history"] == [[2, "stale"]] and lie["sent"] == [] and lie["true"] is False
    assert seen["dependents"] == ["B3"] and seen["born"] == 1
    assert worked_out["sources"] == ["B2"] and worked_out["born"] == 2
    assert worked_out["sent"] == [{"day": 2, "to": 3}]
    assert worked_out["became"] == [{"agent": 3, "id": "B4"}]
    (relayed,) = chains["3"]
    assert relayed["sent"] == [{"day": 3, "to": 4}]  # an imposter's relay counts as passing it on
    assert relayed["became"] == [{"agent": 4, "id": "B5"}]
    assert chains["4"][0]["born"] == 3 and chains["4"][0]["routes"] == [[2, 3]]


# ---- the page ------------------------------------------------------------------------------------


def embedded(page: str):
    start = page.index(DATA_TAG.split("__")[0]) + len(DATA_TAG.split("__")[0])
    return json.loads(page[start : page.index("</script>", start)])


def test_the_page_carries_the_data_and_nothing_in_it_can_end_the_script(tmp_path):
    logs = logged(tmp_path / "logs", ["graph-memory", "B1"])
    data = cascade_data({"graph": logs["graph-memory_s0"], "chat": logs["B1_s0"]})
    data["runs"]["graph"]["model"] = "</script><!-- sneaky"
    page = write_viewer(data, tmp_path / "page.html").read_text()
    assert embedded(page) == data
    assert page.count("</script>") == TEMPLATE.read_text().count("</script>")


def test_a_template_without_the_data_tag_is_refused(tmp_path):
    (tmp_path / "t.html").write_text("<html></html>")
    with pytest.raises(ValueError, match="not the built Cascade page"):
        write_viewer({"scenario": {}, "runs": {}}, tmp_path / "p.html", tmp_path / "t.html")
