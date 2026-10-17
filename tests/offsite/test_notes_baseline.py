"""The baseline: the same offsite team with one shared notes file instead of the graph."""

import pytest

from graph_agent.frame.notes import notes_team
from graph_agent.harness.llm import ChatMessage, ModelReply, ScriptedModel, ToolCall, ToolSchema
from graph_agent.packs.offsite.console import OFFSITE
from graph_agent.packs.offsite.run import build_offsite, run_offsite
from graph_agent.packs.offsite.standin import offsite_team as stand_in
from graph_agent.packs.offsite.teams import offsite_team


def test_the_notes_team_keeps_the_team_and_swaps_only_the_memory():
    graph, notes = offsite_team(), notes_team(offsite_team())
    assert notes.settings.extra["memory"] == "notes"
    assert {n.id for n in graph.nodes} - {n.id for n in notes.nodes} == {"checker"}
    venue = notes.node("venue")
    assert venue.graph_tools == [] and venue.tools == ["venue_booking", "note"]
    assert venue.goals == graph.node("venue").goals  # the same words
    owns = {(link.src, link.dst) for link in notes.links if link.kind == "owns"}
    assert ("venue", "type:Offsite") in owns


def test_every_node_reads_one_shared_notes_file_and_nothing_goes_in_the_graph():
    contexts: dict[str, str] = {}

    def policy(system: str, messages: list[ChatMessage], tools: list[ToolSchema]) -> ModelReply:
        first = messages[0]["content"]
        me = first.split("You are ")[1].split(":")[0]
        contexts.setdefault(me, first)
        if me == "venue" and len(messages) == 1:
            return ModelReply(tool_calls=[ToolCall("note", {"text": "the offsite is Friday"}, "1")])
        return ModelReply(text="done")

    run = run_offsite(ScriptedModel(policy, model="test"), team=notes_team(offsite_team()))
    assert "This team has no knowledge graph" in run.runtime.nodes["venue"].system_prompt()
    for context in contexts.values():
        assert "## Shared notes" in context and "## Beliefs" not in context
    notes = run.runtime.pack.notes().lines  # type: ignore[attr-defined]
    assert sum("Booking LL42 confirmed" in line for line in notes) == 1  # once, not per node
    assert any("venue: the offsite is Friday" in line for line in notes)
    forwarded = [line for line in notes if "Fwd:" in line][0]
    assert "billing@lakeside-lodge-payments.example via pat@team.example" in forwarded
    assert not run.runtime.store.beliefs("venue")


def test_without_the_graph_an_action_built_on_a_moved_date_is_not_held():
    """The same booking, made before the date moves: the graph holds it and tells actions why;
    the notes team gets no such signal and has to notice by itself."""

    def books_a_trip(system: str, messages: list[ChatMessage], tools: list[ToolSchema]):
        first = messages[0]["content"]
        if len(messages) > 1:
            return ModelReply(text="done")
        if (
            "You are venue:" in first
            and "Booking LL42 confirmed" in first
            and "venue:" not in (first.partition("## Shared notes")[2])
        ):
            return ModelReply(
                tool_calls=[ToolCall("note", {"text": "offsite Fri; travel Thu"}, "1")]
            )
        if "You are actions:" in first and "travel_book(" not in first:
            call = ToolCall("travel_book", {"person": "ana", "depart": "Thu 16:00"}, "2")
            return ModelReply(tool_calls=[call])
        return ModelReply(text="done")

    run = run_offsite(ScriptedModel(books_a_trip, model="test"), team=notes_team(offsite_team()))
    assert [t.depart for t in run.world.trips.values() if not t.cancelled] == ["Thu 16:00"]
    assert not [e for e in run.runtime.log.events if e.kind == "held"]

    graph = run_offsite(stand_in())
    assert [e for e in graph.runtime.log.events if e.kind == "held" and e.tick == 4]


def test_old_notes_fall_out_of_a_small_budget():
    runtime, _ = build_offsite(notes_team(offsite_team()), None)
    runtime.start()
    notes = runtime.pack.notes()  # type: ignore[attr-defined]
    for n in range(200):
        notes.write(f"note number {n} about the offsite plans")
    shown = notes.render(200)
    assert "note number 199" in shown and "note number 0 " not in shown
    assert "older notes no longer fit" in shown


def test_the_console_refuses_the_baseline_with_the_stand_in():
    from graph_agent.frame.events import EventLog
    from graph_agent.stores.memory import MemoryStore

    team = OFFSITE.team("offsite", {})
    with pytest.raises(ValueError, match="needs a real model"):
        OFFSITE.start(team, stand_in(), MemoryStore(), EventLog(), {"memory": "notes"})
