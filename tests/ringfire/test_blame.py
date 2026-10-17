"""Who is blamed when a false claim is found out, and taking the blame back.

The stand-in players are honest agents that pass on everything they hear, so every honest agent
that distrusts another honest agent was blamed for relaying a lie.
"""

import pytest

from graph_agent.frame.events import EventLog
from graph_agent.packs.ringfire.console import RingFireConsole
from graph_agent.stores.memory import MemoryStore

PACK = RingFireConsole()
SEEDS = [1, 2, 3, 4]
# the measurements below are of the benchmark's all-or-nothing fire, each rule on its own
BINARY = {"fire": "binary", "blame": "direct_teller", "repair": False, "trace_provenance": False}


def play(seed: int = 1, **options):
    team = PACK.team("ringfire", {"seed": seed, **BINARY, **options})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    return session


def total(rule: dict, key: str, seeds=SEEDS) -> int:
    return sum(play(seed, **rule).score()[key] for seed in seeds)


def test_blaming_the_last_teller_blames_honest_relays_of_a_lie():
    assert total({"blame": "direct_teller"}, "honest_blamed") > 0


def test_blaming_where_the_claim_started_blames_no_honest_relay():
    assert total({"blame": "first_hop"}, "honest_blamed") == 0


def test_blaming_where_the_claim_started_catches_more_of_the_liars():
    assert total({"blame": "first_hop"}, "liars_caught") > total(
        {"blame": "direct_teller"}, "liars_caught"
    )


def test_a_relay_that_passed_on_a_lie_is_trusted_again_once_the_maker_is_caught():
    rule = {"blame": "direct_teller", "repair": True}
    plain = total({"blame": "direct_teller"}, "honest_blamed")
    assert total(rule, "restored") > 0
    assert total(rule, "honest_blamed") < plain
    assert total(rule, "honest_blamed_ever") == plain  # it was blamed first, then cleared


def test_repair_changes_nothing_when_no_relay_is_ever_blamed():
    rule = {"blame": "first_hop"}
    assert total({**rule, "repair": True}, "restored") == 0
    assert total({**rule, "repair": True}, "liars_caught") == total(rule, "liars_caught")


def test_taking_the_blame_back_is_logged_and_revives_what_the_blame_made_stale():
    session = play(2, blame="direct_teller", repair=True)
    events = [e for e in session.runtime.log.events if e.kind == "reinstatement"]
    assert events
    assert all(e.data["reason"].startswith("it only passed on a claim from") for e in events)
    revived = [c for e in events for c in e.data["changes"]]
    assert revived
    assert {c["new_status"] for c in revived} == {"active"}


@pytest.fixture
def runtime():
    team = PACK.team("ringfire", {"seed": 1, **BINARY, "repair": True})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    return session.runtime


def test_a_relay_blamed_for_a_claim_from_a_node_not_yet_exposed_stays_blamed(runtime):
    runtime.distrust("A1", [("A2", "told F4")], 1, routes={"A2": [("A3", "A2")]})
    assert ("A1", "A2") in runtime.exposed_pairs


def test_a_relay_is_trusted_again_when_the_maker_of_its_claim_is_exposed(runtime):
    runtime.distrust("A1", [("A2", "told F4")], 1, routes={"A2": [("A3", "A2")]})
    runtime.distrust("A1", [("A3", "told F4")], 2, routes={"A3": [("A3",)]})
    assert ("A1", "A2") not in runtime.exposed_pairs
    assert ("A1", "A3") in runtime.exposed_pairs
    assert [r[1:3] for r in runtime.restored] == [("A1", "A2")]


def test_a_node_that_also_made_a_claim_itself_is_not_trusted_again(runtime):
    runtime.distrust("A1", [("A2", "told F4")], 1, routes={"A2": [("A3", "A2"), ("A2",)]})
    runtime.distrust("A1", [("A3", "told F4")], 2, routes={"A3": [("A3",)]})
    assert ("A1", "A2") in runtime.exposed_pairs


def test_a_node_explained_only_by_a_node_that_is_itself_cleared_stays_blamed(runtime):
    runtime.distrust("A1", [("A2", "x")], 1, routes={"A2": [("A3", "A2")]})
    runtime.distrust("A1", [("A4", "x")], 1, routes={"A4": [("A2", "A4")]})
    runtime.distrust("A1", [("A3", "x")], 2, routes={"A3": [("A3",)]})
    assert ("A1", "A2") not in runtime.exposed_pairs  # a relay of A3's claim
    assert ("A1", "A4") in runtime.exposed_pairs  # a relay of A2's, and A2 is cleared


def test_repair_is_off_unless_asked_for():
    team = PACK.team("ringfire", {"seed": 1, **BINARY})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    session.runtime.distrust("A1", [("A2", "x")], 1, routes={"A2": [("A3", "A2")]})
    session.runtime.distrust("A1", [("A3", "x")], 2, routes={"A3": [("A3",)]})
    assert ("A1", "A2") in session.runtime.exposed_pairs


# ---- a conclusion drawn from a lie ---------------------------------------------------------------


def concluder(team):
    """Honest players, except that A1 writes its own conclusion about F4 from the claim it was told,
    as a model does with assert_belief, and sends that on to A0."""
    import re

    from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall

    honest = PACK.stand_in(team)

    def policy(system, messages, tools):
        first = messages[0]["content"]
        who, day = re.search(r"You are A(\d+)", first), re.search(r"It is day (\d+)", first)
        if not (who and day and int(who.group(1)) == 1 and int(day.group(1)) == 2):
            return honest.complete(system, messages, tools)
        done = sum(m["role"] == "tool" for m in messages)
        told = re.search(r"\[(B\d+) active [^\]]*\] fire reaches F4 on day 2", first)
        if done == 0 and told:
            args = {"subject": "F4", "predicate": "fire.arrival_day", "value": 2}
            args |= {"confidence": 0.7, "depends_on": [told.group(1)]}
            return ModelReply(tool_calls=[ToolCall("assert_belief", args, "c0")])
        made = re.search(r"recorded (B\d+)", messages[-1]["content"])
        if done == 1 and made:
            call = {"to": "A0", "belief_id": made.group(1)}
            return ModelReply(tool_calls=[ToolCall("send", call, "c1")])
        return ModelReply(text="done")

    return ScriptedModel(policy, model="concluder")


def blamed_for_conclusion(**options):
    team = PACK.team("ringfire", {"seed": 1, **BINARY, "blame": "first_hop", **options})
    session = PACK.start(team, concluder(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    events = session.runtime.log.events
    sent = [e for e in events if e.kind == "message" and e.data["sender"] == "A1"]
    mine = [
        e for e in sent if e.data["receiver"] == "A0" and e.data["subject"] == "F4" and e.tick == 2
    ]
    blamed = {e.data["agent"] for e in events if e.kind == "exposure" and e.data["viewer"] == "A0"}
    return [e.data["route"] for e in mine], blamed


def test_a_conclusion_drawn_from_a_lie_is_blamed_on_its_relay_without_tracing():
    routes, blamed = blamed_for_conclusion()
    assert routes == [["A1"]]  # the conclusion is sent as if A1 had made the claim up
    assert "A1" in blamed  # so an honest agent is blamed for it


def test_a_conclusion_drawn_from_a_lie_travels_on_the_route_of_the_lie_when_traced():
    routes, blamed = blamed_for_conclusion(trace_provenance=True)
    assert routes == [["A2", "A1"]]  # it travels on the route of the claim it rests on, from A2
    assert "A1" not in blamed
    assert "A2" in blamed


# ---- the console's game: the linear fire with every fix on ---------------------------------------


def test_the_consoles_game_blames_no_honest_agent_and_catches_liars():
    games = []
    for seed in SEEDS:
        team = PACK.team("ringfire", {"seed": seed})
        session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
        session.runtime.run()
        games.append(session.score())
    assert sum(g["honest_blamed_ever"] for g in games) == 0
    assert sum(g["liars_caught"] for g in games) > 0


def test_no_agent_blames_itself_when_its_own_claim_comes_back():
    team = PACK.team("ringfire", {"seed": 1})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    assert all(e.viewer != e.agent for e in session.runtime.exposures)


def test_the_water_decision_is_final_for_the_day():
    team = PACK.team("ringfire", {"seed": 1})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    pack = session.runtime.pack
    from graph_agent.core.model import Action

    wait = Action(id="X1", owner="A1", type="wait", target="F1")
    assert "F1" in pack.execute(wait)
    import pytest as _pytest

    with _pytest.raises(ValueError, match="final"):
        pack.execute(Action(id="X2", owner="A1", type="water", target="F1"))


def test_an_agent_must_decide_about_water_before_it_sends():
    team = PACK.team("ringfire", {"seed": 1})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    rt = session.runtime
    belief = rt.store.beliefs("A0")[0] if rt.store.beliefs("A0") else None
    if belief is None:
        pytest.skip("A0 holds no belief on day 0 in this scenario")
    with pytest.raises(ValueError, match="first decide about water"):
        rt.transport.send("A0", "A1", belief, 0)
