"""The three life cases on the frame, with a stand-in team that follows its role cards: one
correction reaches every plan and action built on it, scam senders are quarantined by the whole
team, and nothing outward rests on what a liar said."""

import json

import pytest

from graph_agent.frame.runtime import Item
from graph_agent.frame.spec import TeamSpec, load_team, save_team
from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.packs.life.run import run_life
from graph_agent.packs.life.standin import life_team
from graph_agent.packs.life.teams import TEAMS
from graph_agent.packs.life.world import SCAM_AIRLINE, SCAM_BANK, LifeWorld, minutes, when


@pytest.mark.parametrize("case", ["travel", "promises", "money", "week"])
def test_each_team_leaves_the_week_in_the_right_state(case):
    run = run_life(case, life_team())
    failed = [name for name, ok in run.checks.items() if not ok]
    assert not failed
    assert run.score["unsafe_proposals"] == 0


def test_a_moved_flight_holds_every_action_built_on_it_and_the_team_puts_it_right():
    run = run_life("travel", life_team())
    held = [e.data for e in run.runtime.log.events if e.kind == "held"]
    assert {h["tool"] for h in held} == {"cab_book", "calendar_create", "calendar_move"}
    assert all(h["was_done"] for h in held)
    # one correction at the source, three nodes' graphs changed
    reasons = [
        e.data
        for e in run.runtime.log.events
        if e.kind == "change" and "SK101 departs Fri 07:10" in e.data["reason"]
    ]
    assert {r["viewer"] for r in reasons} == {"travel", "calendar", "actions"}
    cabs = [c for c in run.world.cabs.values() if not c.cancelled]
    assert [c.pickup for c in cabs] == ["Fri 03:40"]
    assert run.world.events["ev-dana-call"].start == "Thu 16:00"


def test_a_scam_sender_is_quarantined_by_the_whole_team_once_one_node_checks():
    run = run_life("week", life_team())
    for scam in (SCAM_AIRLINE, SCAM_BANK):
        nodes = {v for v, a in run.runtime.exposed_pairs if a == scam}
        assert nodes == {"inbox", "travel", "calendar", "people", "money", "actions"}
    first = [e for e in run.runtime.exposures if e.agent == SCAM_AIRLINE][0]
    assert first.viewer == "travel" and "checked" in first.reason
    assert not run.world.payments


def test_a_renegotiated_promise_moves_its_task_and_a_kept_one_is_closed():
    run = run_life("promises", life_team())
    tasks = sorted((t.title, t.due, t.done) for t in run.world.tasks.values())
    assert ("promise-deck: keep the promise", "Mon 17:00", False) in tasks
    assert all(done for title, _, done in tasks if "review" in title)


def test_the_teams_are_team_files(tmp_path):
    for name, make in TEAMS.items():
        team = make()
        save_team(team, tmp_path / f"{name}.json")
        assert load_team(tmp_path / f"{name}.json") == team
        assert isinstance(team, TeamSpec)
        actions = team.node("actions")
        reads_mail = [n.id for n in team.nodes if "mail_read" in n.tools]
        assert "mail_read" not in actions.tools and "bank_pay" in actions.tools
        assert all("bank_pay" not in team.node(n).tools for n in reads_mail)


def test_model_extraction_reads_claims_from_the_text():
    gold = {
        "m1": {"about": ["SK101"], "claims": [["SK101", "flight.departs", "Thu 18:40"]]},
        "m4": {
            "about": ["SK101"],
            "claims": [
                ["SK101", "flight.departs", "Fri 07:10"],
                ["nowhere", "flight.departs", "x"],
            ],
        },
    }

    def policy(system, messages, tools):
        text = messages[0]["content"]
        if "## Role" in text:
            return ModelReply(text="done")
        for mail_id, reply in gold.items():
            if ("Thu 18:40" in text and mail_id == "m1" and "Schedule change" not in text) or (
                "Schedule change" in text and mail_id == "m4"
            ):
                return ModelReply(text="Here: " + json.dumps(reply))
        return ModelReply(text="no claims")

    run = run_life("travel", ScriptedModel(policy), extraction="model")
    assert run.pack.extracted["m1"] == [("SK101", "flight.departs", "Thu 18:40")]
    assert run.pack.extracted["m4"] == [("SK101", "flight.departs", "Fri 07:10")]  # unknown dropped
    assert 0 < run.score["extraction_recall"] < 1 and run.score["extraction_precision"] == 1
    travel = [b for b in run.runtime.store.beliefs("travel") if b.predicate == "flight.departs"]
    assert [(b.value, b.status) for b in travel] == [
        ("Thu 18:40", "retracted"),
        ("Fri 07:10", "active"),
    ]


def test_times_and_ticks():
    assert minutes("Fri 07:10") - minutes("Thu 18:40") == 750
    assert when(minutes("Fri 07:10") - 210) == "Fri 03:40"
    world = LifeWorld()
    assert world.departure() == "Thu 18:40"
    world.tick = 4
    assert world.departure() == "Fri 07:10"
    assert world.booking("ABC123")["payment_due"] == 0


def test_tools_from_a_real_mcp_server_work_the_same():
    pytest.importorskip("mcp")
    local = run_life("week", life_team())
    remote = run_life("week", life_team(), tools="mcp")
    assert remote.checks == local.checks
    assert remote.score["actions_done"] == local.score["actions_done"]
    assert remote.score["quarantined"] == local.score["quarantined"]


def test_a_plan_nobody_has_received_is_listed_until_it_is_sent():
    from graph_agent.frame.nodes import AgentNode
    from graph_agent.packs.life.run import build_life

    runtime, _, pack = build_life(TEAMS["promises"](), None)
    runtime.start()
    runtime.ensure_entity("promise-deck", "Promise")
    people = runtime.nodes["people"]
    assert isinstance(people, AgentNode)
    (due,) = runtime.route(
        Item(
            id="s1",
            kind="sent",
            tick=0,
            source="me",
            about=["promise-deck"],
            claims=[("promise-deck", "promise.due", "Mon 17:00")],
        ),
        ["people"],
    )["people"]
    plan = people.box.assert_belief("promise-deck", "plan.task_due", "Mon 17:00", [due.id]).split()[
        -1
    ]
    context = pack.context(runtime.team.node("people"), 0, 3500)
    assert f'send(to="actions", belief_id="{plan}")' in context
    runtime.send("people", "actions", runtime.store.belief("people", plan))
    assert (
        plan not in pack.context(runtime.team.node("people"), 0, 3500).partition("not sent yet")[2]
    )


def test_amounts_a_model_reads_are_numbers_so_an_honest_nothing_due_is_not_a_lie():
    from graph_agent.packs.life.pack import normalise

    assert normalise("booking.payment_due", "none") == 0.0
    assert normalise("booking.payment_due", "Nothing") == 0.0
    assert normalise("booking.payment_due", "49.00") == 49.0
    assert normalise("subscription.next_price", "$12.99") == 12.99
    assert normalise("flight.departs", " Fri 07:10 ") == "Fri 07:10"
    run = run_life("week", life_team())
    assert run.score["honest_quarantined"] == 0


def test_a_check_reading_back_the_teams_own_action_confirms_it_instead_of_holding_it(monkeypatch):
    run = run_life("money", life_team())
    events = run.runtime.log.events
    confirmed = [e.data for e in events if e.kind == "confirmed"]
    assert {e["tool"] for e in confirmed} == {"subscription_set_card"}
    assert not [e for e in events if e.kind == "held" and e.data["tool"] == "subscription_set_card"]
    assert all(run.checks.values())
    # the old reading is still retired, and its plans say why
    reasons = [str(e.data["reason"]) for e in events if e.kind == "change"]
    assert any("the team's own action" in r for r in reasons)

    # without the tool's effect, the same week holds the card moves although they were right
    from graph_agent.packs.life import tools

    original = tools.LifeTools.list_tools

    def without_effects(self: tools.LifeTools) -> list[tools.ToolSpec]:
        from dataclasses import replace

        return [replace(t, effects=None) for t in original(self)]

    monkeypatch.setattr(tools.LifeTools, "list_tools", without_effects)
    blind = run_life("money", life_team())
    held = [e for e in blind.runtime.log.events if e.kind == "held"]
    assert {e.data["tool"] for e in held} == {"subscription_set_card"}
