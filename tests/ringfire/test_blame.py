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


def test_imposters_that_keep_lying_tell_neighbours_a_false_alarm_about_their_own_field():
    team = PACK.team("ringfire", {"seed": 17, "liars": "5,7", "keep_lying": True, "extra_links": 0})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    game = session.runtime.pack.game
    lies = [m for m in game.net.log if m.sender in (5, 7) and m.day > 1 and m.route == (m.sender,)]
    assert lies
    for m in lies:
        assert m.claim.field_id == m.receiver and m.claim.day == m.day + 1
        assert m.claim.day not in game.sim.fields[m.claim.field_id].ignitions  # it was false


def test_a_burning_field_wakes_its_keeper_in_wake_mode():
    team = PACK.team("ringfire", {"seed": 1, "wake": True})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    pack = session.runtime.pack
    burning = [f.owner for f in pack.game.sim.fields if f.state.value == "burning"]
    assert burning and all(pack.needs_turn(f"A{a}", 0) for a in burning)


# ---- finding other agents (the linear game) ------------------------------------------------------


def started(**options):
    team = PACK.team("ringfire", {"seed": 3, "liars": "5,7", **options})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.start()
    return team, session.runtime


def test_the_liars_can_be_chosen():
    team, _ = started()
    assert {n.id for n in team.nodes if "imposter" in n.label} == {"A5", "A7"}


def test_an_agent_can_look_up_the_others_and_see_whom_it_is_linked_to():
    team, rt = started()
    tool = rt.tools_for(next(n for n in team.nodes if n.id == "A6"))[0]
    text = tool.handler({})
    assert text.splitlines()[0] == "You are A6. Linked to: A5, A7"
    assert "A4: keeps F4 · 2 step(s) round the ring · not linked · trusted" in text
    assert tool.handler({"field": "F4"}).splitlines()[1].startswith("A4: keeps F4")


def test_nobody_is_told_whom_to_link_to_in_the_linear_game():
    team, rt = started()
    rt.distrust("A6", [("A5", "lied"), ("A7", "lied")], 1)
    context = rt.pack.context_for(6, 1, 4000)
    assert 'act(type="link"' not in context
    assert "find_agents" in context  # the role card says the tool exists, not what to do with it


def test_the_benchmark_game_keeps_its_link_hints_and_has_no_directory():
    team, rt = started(fire="binary")
    assert all(not n.tools for n in team.nodes)
    rt.distrust("A6", [("A5", "lied")], 1)
    assert 'act(type="link", target="A4")' in rt.pack.context_for(6, 1, 4000)


def test_liars_are_still_caught_when_fires_are_being_put_out_all_round_the_ring():
    team = PACK.team("ringfire", {"seed": 16, "liars": "5,7", "keep_lying": True, "extra_links": 0})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    score = session.score()
    assert score["liars_caught"] >= 2  # A6, A4 and A0 hear the lies straight from A5 and A7
    assert score["honest_blamed_ever"] == 0


# ---- building a bigger network: at most 3 links, and a track record per source ------------------


def act(rt, owner, kind, target):
    from graph_agent.core.model import Action

    return rt.pack.execute(
        Action(id=f"X-{owner}-{kind}-{target}", owner=owner, type=kind, target=target)
    )


def test_an_agent_can_link_to_a_third_agent_but_not_a_fourth():
    _, rt = started(extra_links=0)
    assert act(rt, "A6", "link", "A4") == "you are now linked to A4"
    with pytest.raises(ValueError, match="already talk to 3"):
        act(rt, "A6", "link", "A0")


def test_a_link_needs_a_free_place_on_both_sides():
    _, rt = started(extra_links=0)
    act(rt, "A2", "link", "A4")  # A4 now talks to A3, A5 and A2
    with pytest.raises(ValueError, match="A4 already talks to 3"):
        act(rt, "A6", "link", "A4")


def test_unlinking_makes_room_and_cuts_the_liar_off():
    _, rt = started(extra_links=0)
    act(rt, "A6", "link", "A4")
    assert act(rt, "A6", "unlink", "A7") == "you are no longer linked to A7"
    assert act(rt, "A6", "link", "A0") == "you are now linked to A0"
    assert sorted(rt.network.neighbours("A6")) == ["A0", "A4", "A5"]


def test_scripted_lies_do_not_reach_an_agent_that_unlinked_the_liar():
    team = PACK.team("ringfire", {"seed": 16, "liars": "5,7", "keep_lying": True, "extra_links": 0})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    rt = session.runtime
    rt.start()
    act(rt, "A6", "unlink", "A5")
    act(rt, "A6", "unlink", "A7")
    while not rt.finished():
        rt.step()
    told_a6 = [e for e in rt.log.events if e.kind == "message" and e.data["receiver"] == "A6"]
    assert not any(e.data["sender"] in ("A5", "A7") for e in told_a6)


def test_the_track_record_credits_where_a_claim_started_not_who_relayed_it():
    team = PACK.team("ringfire", {"seed": 16, "liars": "5,7", "keep_lying": True, "extra_links": 0})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    rt = session.runtime
    rt.run()
    record = rt.pack.track_record(6, rt.tick)
    assert record.get("A5", (0, 0))[1] > 0 or record.get("A7", (0, 0))[1] > 0  # their own lies
    assert all(wrong == 0 for a, (_, wrong) in record.items() if a not in ("A5", "A7"))


# ---- reports carry the fire's strength; the outlook ignores fires known to be out --------------


def played(days: int, seed: int = 17):
    team = PACK.team(
        "ringfire", {"seed": seed, "liars": "5,7", "keep_lying": True, "extra_links": 0}
    )
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    rt = session.runtime
    rt.start()
    for _ in range(days):
        rt.step()
    return rt


def test_a_report_of_a_fire_seen_carries_its_strength_or_says_it_was_put_out():
    rt = played(8)
    honest = [m for m in rt.pack.game.net.log if m.sender not in (5, 7) and m.route[0] == m.sender]
    assert honest
    assert all(m.claim.strength is not None for m in honest)
    assert any(m.claim.strength == 0 for m in honest) or any(m.claim.strength > 0 for m in honest)


def test_the_outlook_does_not_forecast_from_a_fire_known_to_be_out():
    rt = played(6)
    pack = rt.pack
    for n in range(8):
        news = pack.fire_news(n, rt.tick)
        out_fields = {f for f, (_, strength, _) in news.items() if strength == 0}
        for line in pack.linear_outlook(n, rt.tick):
            if line.startswith("  (put out"):
                continue
            assert not any(f" F{f} was burning" in line for f in out_fields)


def test_the_context_says_whose_reports_could_not_be_believed_and_why():
    rt = played(10)
    rt.distrust("A6", [("A5", "lied")], rt.tick)
    context = rt.pack.linear_context(6, rt.tick)
    assert "fire from its field reaches yours in" in context
    assert "## Fire outlook (the latest you know of each fire" in context


# ---- outages and network points ---------------------------------------------------------------


def test_an_offline_agent_takes_no_turn_and_cannot_be_messaged():
    _, rt = started(extra_links=0)
    rt.pack.offline[6] = 3  # A6 is offline until day 3
    a6 = next(n for n in rt.nodes.values() if n.id == "A6")
    assert not a6.wants_turn(0)
    belief = rt.store.beliefs("A5")[0] if rt.store.beliefs("A5") else None
    rt.pack.decided.add(5)
    if belief is not None:
        with pytest.raises(ValueError, match="A6 is offline until day 3"):
            rt.transport.send("A5", "A6", belief, 0)


def test_outages_happen_in_a_long_game_and_last_two_days():
    team = PACK.team("ringfire", {"seed": 17, "outages": 0.5})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    outages = [e for e in session.runtime.log.events if e.kind == "offline"]
    assert outages
    assert all(e.data["until"] == e.tick + 2 for e in outages)


def test_network_points_count_trusted_online_links_each_night():
    team = PACK.team("ringfire", {"seed": 17, "outages": 0.0, "days": 3})
    session = PACK.start(team, PACK.stand_in(team), MemoryStore(), EventLog(), {})
    session.runtime.run()
    pack = session.runtime.pack
    honest = [a for a in range(8) if a not in pack.game.net.imposters]
    assert all(pack.network_points[a] >= 2 for a in honest)  # two neighbours, trusted, online


def test_an_arrival_day_must_be_a_whole_number():
    from graph_agent.core.tools import Toolbox

    rt = played(0, seed=17)  # the fire starts at F4, so A4 has seen it
    seen = [b for b in rt.store.beliefs("A4") if b.origin == "observed"]
    box = Toolbox(rt.store, rt.ids, "A4", rt.pack.predicates)
    with pytest.raises(ValueError, match="whole number"):
        box.assert_belief("F5", "fire.arrival_day", "6 (unconfirmed)", [seen[0].id])
    assert box.assert_belief("F5", "fire.arrival_day", "6", [seen[0].id]).startswith("recorded")
