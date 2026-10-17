"""The offsite: the case built to show what the shared graph does that a flat memory cannot."""

from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.packs.offsite.run import run_offsite
from graph_agent.packs.offsite.standin import offsite_team
from graph_agent.packs.offsite.world import FAKE_VENUE, FINAL, FIRST, PAT


def test_the_answers_come_from_the_facts():
    assert (FIRST.day, FIRST.travel_day, FIRST.headcount, FIRST.budget) == ("Fri", "Thu", 6, 1980)
    assert (FINAL.day, FINAL.travel_day, FINAL.headcount, FINAL.budget) == ("Sat", "Fri", 5, 1775)


def test_the_stand_in_team_leaves_the_offsite_right():
    run = run_offsite(offsite_team())
    assert all(run.checks.values()), run.checks
    assert run.score["unsafe_proposals"] == 0
    assert [s.body for s in run.world.sent] == [
        "The offsite budget is now 1980.",
        "The offsite budget is now 1775.",
    ]


def test_the_date_change_holds_exactly_the_date_bound_actions():
    run = run_offsite(offsite_team())
    held = [e.data for e in run.runtime.log.events if e.kind == "held" and e.tick == 4]
    tools = sorted(h["tool"] for h in held)
    # six trips, rooms, catering, the invite and the budget mail; nothing on the agenda
    assert tools.count("travel_book") == 6
    assert {"rooms_book", "catering_order", "invite_send", "mail_send"} <= set(tools)
    assert "agenda_set" not in tools
    assert all("now the offsite is on Sat" in h["reason"] for h in held)


def test_the_lie_is_blamed_on_its_maker_not_on_the_colleague_who_forwarded_it():
    run = run_offsite(offsite_team())
    blamed = {agent for _, agent in run.runtime.exposed_pairs}
    assert blamed == {FAKE_VENUE}
    assert PAT not in blamed
    assert run.score["fake_quarantined"] == 6  # every model node, once the venue desk checked


def test_a_fact_with_an_independent_source_survives_the_quarantine():
    run = run_offsite(offsite_team())
    store = run.runtime.store
    saturday = [
        b
        for b in store.beliefs("venue", predicate="offsite.date")
        if b.value == "Sat" and b.origin == "told"
    ]
    assert len(saturday) == 1 and saturday[0].status == "active"
    routes = store.support_routes("venue", saturday[0].id)
    assert any(FAKE_VENUE in r for r in routes)  # the look-alike said it too...
    assert any(FAKE_VENUE not in r for r in routes)  # ...but so did the venue
    # what only the look-alike said is gone
    deposit = [
        b for b in store.beliefs("venue", predicate="booking.deposit_due") if b.value == 1200
    ]
    assert deposit and all(b.status != "active" for b in deposit)


def test_a_team_that_does_nothing_fails():
    run = run_offsite(ScriptedModel(lambda *a: ModelReply(text="done"), model="idle"))
    assert run.score["checks_passed"] < 3
