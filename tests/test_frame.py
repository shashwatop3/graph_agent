"""The frame on its own, with a toy domain: team files, routing, triggers, the transport, the
checker and its blame policies, warnings, and outward actions that wait for approval and are held
when what they rest on changes."""

import pytest
from pydantic import ValidationError

from graph_agent.core.registry import Predicate
from graph_agent.frame.nodes import approvals, catalogue_info
from graph_agent.frame.pack import BasePack
from graph_agent.frame.runtime import Item, Runtime
from graph_agent.frame.spec import LinkSpec, NodeSpec, Settings, TeamSpec, Trigger
from graph_agent.frame.tools import ToolSpec, schema_of
from graph_agent.harness.llm import ModelReply, ScriptedModel, ToolCall
from graph_agent.stores.memory import MemoryStore

PREDICATES = {"status": Predicate(name="status", single_valued=True)}
TEMPLATES = {"status": "{subject} is {value}"}


def team(*nodes: NodeSpec, links=(), **settings) -> TeamSpec:
    return TeamSpec(name="toy", nodes=list(nodes), links=list(links), settings=Settings(**settings))


def runtime(spec: TeamSpec, client=None, **pack_args) -> Runtime:
    pack = BasePack(PREDICATES, TEMPLATES, **pack_args)
    rt = Runtime(spec, pack, MemoryStore(), client)
    pack.rt = rt
    return rt


def item(id_, source, subject, value, tick=0, to=None) -> Item:
    return Item(
        id=id_,
        kind="note",
        tick=tick,
        source=source,
        about=[subject],
        to=to,
        claims=[(subject, "status", value)],
    )


def quiet() -> ScriptedModel:
    return ScriptedModel(lambda system, messages, tools: ModelReply(text="ok"))


# ---- the team file ------------------------------------------------------------------------------


def test_a_team_file_is_checked():
    with pytest.raises(ValidationError, match="unique"):
        team(NodeSpec(id="a", type="agent"), NodeSpec(id="a", type="agent"))
    with pytest.raises(ValidationError, match="unknown node"):
        team(NodeSpec(id="a", type="agent"), links=[LinkSpec(kind="talks_to", src="a", dst="b")])
    with pytest.raises(ValueError, match="unknown type"):
        runtime(team(NodeSpec(id="a", type="no-such-node")))


def test_the_catalogue_describes_every_node_type():
    types = {entry["type"]: entry for entry in catalogue_info()}
    assert {"schedule", "stream", "router", "agent", "responder", "checker", "warner"} <= set(types)
    assert types["agent"]["kind"] == "model" and types["stream"]["kind"] == "source"


# ---- items reach the owners of what they are about ----------------------------------------------


def test_an_item_goes_to_whoever_owns_what_it_is_about():
    spec = team(
        NodeSpec(id="mail", type="stream", config={"feed": "mail"}),
        NodeSpec(id="router", type="router", config={"fallback": "inbox"}),
        NodeSpec(id="travel", type="agent", triggers=[Trigger(on="item")]),
        NodeSpec(id="money", type="agent", triggers=[Trigger(on="item")]),
        NodeSpec(id="inbox", type="agent", triggers=[Trigger(on="item")]),
        links=[
            LinkSpec(kind="feeds", src="mail", dst="router"),
            LinkSpec(kind="owns", src="travel", dst="type:Flight"),
            LinkSpec(kind="owns", src="money", dst="card-1"),
        ],
    )
    rt = runtime(spec, quiet())
    rt.ensure_entity("AI101", "Flight")
    rt.ensure_entity("card-1", "Card")
    rt.feeds["mail"] = lambda tick: (
        [item("m1", "airline", "AI101", "on time"), item("m2", "x", "lottery", "won")]
        if tick == 0
        else []
    )
    rt.run(max_ticks=2)
    routed = {e.data["item"]: e.data["to"] for e in rt.log.events if e.kind == "item"}
    assert routed == {"m1": ["travel"], "m2": ["inbox"]}
    assert [b.value for b in rt.store.beliefs("travel")] == ["on time"]
    turns = [(t, node) for t, node, _ in rt.turns]
    assert (1, "travel") in turns and (1, "inbox") in turns
    assert all(node != "money" for _, node in turns)  # nothing reached it: it never woke


def test_a_told_claim_keeps_its_source_on_the_route():
    rt = runtime(team(NodeSpec(id="a", type="agent")))
    rt.start()
    (belief,) = rt.route(item("m1", "airline", "AI101", "on time"), ["a"])["a"]
    assert belief.origin == "told"
    assert rt.store.support_routes("a", belief.id) == [("airline",)]


def test_a_source_that_changes_its_mind_retires_what_it_said_and_flags_what_rested_on_it():
    rt = runtime(team(NodeSpec(id="a", type="agent")))
    rt.start()
    (old,) = rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])["a"]
    rt.ensure_entity("cab", "Booking")
    rt.nodes["a"].box.now = 0  # type: ignore[attr-defined]
    reply = rt.nodes["a"].box.assert_belief("cab", "status", "15:30", [old.id])  # type: ignore[attr-defined]
    plan = reply.split()[-1]
    rt.tick = 1
    rt.route(item("m2", "airline", "AI101", "07:10", tick=1), ["a"])
    assert rt.store.belief("a", old.id).status == "retracted"
    assert rt.store.belief("a", plan).status == "suspect"
    changes = [e.data for e in rt.log.events if e.kind == "change"]
    assert {c["belief"] for c in changes} == {old.id, plan}
    assert "airline updated it" in changes[0]["reason"]


def test_someone_else_saying_otherwise_does_not_retire_a_claim():
    rt = runtime(team(NodeSpec(id="a", type="agent")))
    rt.start()
    (old,) = rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])["a"]
    rt.route(item("m2", "scam", "AI101", "cancelled"), ["a"])
    assert rt.store.belief("a", old.id).status == "active"


# ---- the transport ------------------------------------------------------------------------------


def test_messages_travel_only_over_links_and_carry_the_route():
    spec = team(
        NodeSpec(id="a", type="agent"),
        NodeSpec(id="b", type="agent"),
        NodeSpec(id="c", type="agent"),
        links=[
            LinkSpec(kind="talks_to", src="a", dst="b"),
            LinkSpec(kind="talks_to", src="b", dst="c"),
        ],
    )
    rt = runtime(spec)
    rt.start()
    (seen,) = rt.route(item("m1", "airline", "AI101", "on time"), ["a"])["a"]
    assert rt.send("a", "b", seen) == "sent to b"
    told = rt.store.beliefs("b")[0]
    rt.send("b", "c", told)
    assert rt.store.support_routes("c", rt.store.beliefs("c")[0].id) == [("airline", "a", "b")]
    with pytest.raises(ValueError, match="not linked"):
        rt.send("a", "c", seen)


def test_messages_sent_during_the_turns_arrive_after_all_of_them():
    sends = {"a": 0}

    def policy(system, messages, tools):
        me = messages[0]["content"].split(":")[0].removeprefix("## Role\nYou are ")
        if me == "a" and sends["a"] == 0 and "B1" in messages[0]["content"]:
            sends["a"] += 1
            return ModelReply(tool_calls=[ToolCall("send", {"to": "b", "belief_id": "B1"}, "1")])
        return ModelReply(text="done")

    spec = team(
        NodeSpec(id="a", type="agent"),
        NodeSpec(id="b", type="agent"),
        links=[LinkSpec(kind="talks_to", src="a", dst="b")],
    )
    rt = runtime(spec, ScriptedModel(policy), observed_sources=["sensor"])
    rt.start()
    rt.route(item("s1", "sensor", "door", "open"), ["a"])
    seen_by_b: list[str] = []
    rt.after_tick.append(lambda tick: seen_by_b.append(str(len(rt.store.beliefs("b")))))
    rt.step()
    kinds = [e.kind for e in rt.log.events]
    assert kinds.index("message") > max(i for i, k in enumerate(kinds) if k == "turn")
    assert seen_by_b == ["1"]


# ---- the checker --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "policy, blamed",
    [("direct_teller", {"b"}), ("whole_route", {"liar", "b"}), ("first_hop", {"liar"})],
)
def test_evidence_refutes_a_told_claim_and_blames_by_policy(policy, blamed):
    spec = team(
        NodeSpec(id="a", type="agent"),
        NodeSpec(id="b", type="agent"),
        NodeSpec(id="checker", type="checker"),
        links=[LinkSpec(kind="talks_to", src="a", dst="b")],
        blame=policy,
    )
    rt = runtime(spec, observed_sources=["sensor"])
    rt.start()
    (lie,) = rt.route(item("m1", "liar", "door", "locked"), ["b"])["b"]
    rt.send("b", "a", lie)
    rt.route(item("s1", "sensor", "door", "open"), ["a"])
    assert {e.agent for e in rt.exposures if e.viewer == "a"} == blamed
    told = [b for b in rt.store.beliefs("a") if b.origin == "told"][0]
    assert told.status == "stale"


def test_a_message_that_contradicts_what_the_receiver_saw_is_caught_on_arrival():
    spec = team(
        NodeSpec(id="a", type="agent"),
        NodeSpec(id="b", type="agent"),
        NodeSpec(id="checker", type="checker"),
        links=[LinkSpec(kind="talks_to", src="a", dst="b")],
    )
    rt = runtime(spec, observed_sources=["sensor"])
    rt.start()
    rt.route(item("s1", "sensor", "door", "open"), ["a"])
    (lie,) = rt.route(item("m1", "liar", "door", "locked"), ["b"])["b"]
    rt.send("b", "a", lie)
    assert [(e.viewer, e.agent) for e in rt.exposures] == [("a", "b")]


# ---- outward actions ----------------------------------------------------------------------------


def booking_tool(log: list[str]) -> ToolSpec:
    def book(arguments: dict) -> str:
        log.append(arguments["what"])
        return f"booked {arguments['what']}"

    return ToolSpec(
        "cab.book",
        "Book a cab.",
        schema_of({"what": {"type": "string"}}, ["what"]),
        book,
        outward=True,
    )


class Provider:
    def __init__(self, tools):
        self.tools = tools

    def list_tools(self):
        return self.tools


def test_an_outward_action_waits_for_approval_and_is_held_when_its_basis_changes():
    booked: list[str] = []

    def policy(system, messages, tools):
        if any(m["role"] == "tool" for m in messages):
            return ModelReply(text="done")
        assert "cab.book" in [t["name"] for t in tools]
        call = ToolCall("cab.book", {"what": "15:30", "depends_on": ["B1"]}, "1")
        return ModelReply(tool_calls=[call])

    spec = team(
        NodeSpec(id="a", type="agent", tools=["cab.*"], triggers=[Trigger(on="item")]),
        NodeSpec(id="r", type="responder"),
        links=[LinkSpec(kind="watches", src="r", dst="a")],
        approvals="manual",
    )
    rt = runtime(spec, ScriptedModel(policy))
    rt.providers.append(Provider([booking_tool(booked)]))
    rt.start()
    rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])
    rt.step()
    (proposal,) = approvals(rt).proposals.values()
    assert proposal.status == "pending" and booked == []
    assert approvals(rt).decide(proposal.id, True) == "P1: booked 15:30"
    assert booked == ["15:30"] and proposal.status == "done"
    rt.route(item("m2", "airline", "AI101", "07:10", tick=1), ["a"])
    assert proposal.status == "held" and "already carried out" in proposal.note
    held = [e for e in rt.log.events if e.kind == "held"]
    assert held and held[0].data["broken"] == ["B1"]
    assert "change" in rt.pending["r"]  # the responder wakes on the cascade


def test_auto_approval_runs_an_outward_action_at_once():
    booked: list[str] = []
    rt = runtime(team(NodeSpec(id="a", type="agent", tools=["cab.book"])))
    rt.providers.append(Provider([booking_tool(booked)]))
    rt.start()
    tools = rt.nodes["a"].tools()  # type: ignore[attr-defined]
    assert tools.call("cab.book", {"what": "now"}) == "P1: booked now"
    assert tools.call("cab.book", {"what": "x", "depends_on": ["B9"]}).startswith("error:")


def test_a_node_only_gets_the_tools_it_is_allowed():
    rt = runtime(team(NodeSpec(id="a", type="agent", tools=["mail.read"])))
    rt.providers.append(
        Provider(
            [
                ToolSpec("mail.read", "Read.", schema_of({}), lambda a: "a mail"),
                ToolSpec("mail.send", "Send.", schema_of({}), lambda a: "sent", outward=True),
            ]
        )
    )
    names = rt.nodes["a"].tools().names  # type: ignore[attr-defined]
    assert "mail.read" in names and "mail.send" not in names and "recall" in names


# ---- triggers -----------------------------------------------------------------------------------


def test_schedule_and_due_triggers():
    spec = team(
        NodeSpec(id="weekly", type="agent", triggers=[Trigger(on="schedule", every=3, at=1)]),
        NodeSpec(id="due", type="agent", triggers=[Trigger(on="due", within=1)]),
        links=[LinkSpec(kind="owns", src="due", dst="bill")],
    )
    rt = runtime(spec, quiet(), observed_sources=["bank"])
    rt.start()
    rt.ensure_entity("bill", "Bill")
    rt.route(
        Item(
            id="b",
            kind="bill",
            tick=0,
            source="bank",
            about=["bill"],
            claims=[("bill", "status", 4)],
        ),
        ["due"],
    )
    rt.pending.clear()
    for _ in range(6):
        rt.step()
    turns = [(t, n) for t, n, _ in rt.turns]
    assert [t for t, n in turns if n == "weekly"] == [1, 4]
    assert [t for t, n in turns if n == "due"] == [3, 4]


# ---- corrections reach every copy; scams are quarantined; old evidence is not a refutation ------


def three_in_a_row(**settings) -> Runtime:
    spec = team(
        NodeSpec(id="a", type="agent"),
        NodeSpec(id="b", type="agent"),
        NodeSpec(id="c", type="agent"),
        NodeSpec(id="checker", type="checker"),
        links=[
            LinkSpec(kind="talks_to", src="a", dst="b"),
            LinkSpec(kind="talks_to", src="b", dst="c"),
        ],
        **settings,
    )
    rt = runtime(spec, observed_sources=["sensor"])
    rt.start()
    return rt


def test_a_correction_at_the_source_withdraws_every_copy_down_the_line():
    rt = three_in_a_row()
    rt.ensure_entity("plan", "Plan")
    (fact,) = rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])["a"]
    rt.send("a", "b", fact)
    copy_b = rt.store.beliefs("b")[0]
    rt.send("b", "c", copy_b)
    copy_c = rt.store.beliefs("c")[0]
    box = rt.nodes["c"].box  # type: ignore[attr-defined]
    plan = box.assert_belief("plan", "status", "cab at 15:10", [copy_c.id]).split()[-1]
    rt.route(item("m2", "airline", "AI101", "07:10", tick=1), ["a"])
    assert rt.store.belief("b", copy_b.id).status == "retracted"
    assert rt.store.belief("c", copy_c.id).status == "retracted"
    assert rt.store.belief("c", plan).status == "suspect"


def test_a_copy_with_its_own_route_is_kept():
    rt = three_in_a_row()
    (fact,) = rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])["a"]
    rt.send("a", "b", fact)
    rt.route(item("m1b", "airport", "AI101", "18:40"), ["b"])  # b also heard it independently
    copy_b = [b for b in rt.store.beliefs("b") if b.origin == "told"][0]
    rt.retract("a", fact.id, 1, "changed my mind")
    assert rt.store.belief("b", copy_b.id).status == "active"


def test_sending_what_the_receiver_already_has_is_refused():
    rt = three_in_a_row()
    (fact,) = rt.route(item("m1", "airline", "AI101", "18:40"), ["a"])["a"]
    rt.send("a", "b", fact)
    with pytest.raises(ValueError, match="already has this"):
        rt.send("a", "b", fact)


def test_one_node_catching_a_scam_sender_blocks_it_for_the_whole_team():
    rt = three_in_a_row(quarantine="team")
    rt.route(item("m1", "scam", "account", "locked"), ["a"])
    rt.route(item("s1", "sensor", "account", "ok"), ["a"])
    assert {v for v, agent in rt.exposed_pairs if agent == "scam"} == {"a", "b", "c"}
    reasons = [e.reason for e in rt.exposures]
    assert reasons[1].startswith("quarantined by a: ") and "quarantined by b" not in reasons[2]


def test_old_evidence_does_not_make_a_newer_claim_a_lie():
    rt = three_in_a_row()
    rt.route(item("s1", "sensor", "AI101", "18:40", tick=0), ["a"])
    rt.tick = 4
    rt.route(item("m4", "airline", "AI101", "07:10", tick=4), ["a"])  # the world moved on
    assert not rt.exposures
    rt.route(item("s2", "sensor", "AI101", "07:10", tick=4), ["a"])  # a fresh check agrees
    assert not rt.exposures
    old = [b for b in rt.store.beliefs("a") if b.value == "18:40"][0]
    assert old.status == "retracted"  # the newer reading retired the old one


def test_a_checking_tool_records_evidence_for_whoever_called_it():
    rt = runtime(team(NodeSpec(id="a", type="agent", tools=["check"])))
    rt.providers.append(
        Provider(
            [
                ToolSpec(
                    "check",
                    "Check.",
                    schema_of({}),
                    lambda a: "ok",
                    observes=lambda a, r: [("account", "status", r)],
                )
            ]
        )
    )
    rt.start()
    assert rt.nodes["a"].tools().call("check", {}) == "ok"  # type: ignore[attr-defined]
    (belief,) = rt.store.beliefs("a")
    assert (belief.subject, belief.value, belief.origin) == ("account", "ok", "observed")
