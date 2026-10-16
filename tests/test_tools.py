"""The eight agent tools, on every store."""

import pytest

from graph_agent.adapters import ringfire as rf
from graph_agent.core.compiler import compile_context
from graph_agent.core.ids import Ids
from graph_agent.core.tools import TOOL_NAMES, Toolbox
from graph_agent.stores.memory import MemoryStore
from stores_param import STORES

N = 6


@pytest.fixture(params=STORES)
def store(request):
    store = request.param()
    rf.setup_map(store, N, [(f, f) for f in range(N)], [(f, (f + 1) % N, 1) for f in range(N)])
    yield store
    store.close()


def toolbox(store, ids=None, viewer="A3", now=3, **kw) -> Toolbox:
    """`ids` must be the same Ids the adapter used to create the beliefs (see Toolbox)."""
    box = Toolbox(store, viewer, rf.PREDICATES, rf.TEMPLATES, ids or Ids(), **kw)
    box.now = now
    return box


def told(store, ids, day, sender=2, route=(0, 1, 2), receiver=3, field=3, sent_on=0):
    return rf.record_message(
        store,
        ids,
        {
            "sender": sender,
            "receiver": receiver,
            "route": list(route),
            "day": sent_on,
            "claim": {"field_id": field, "day": day},
        },
    )


def evidence(store, ids, day, field, viewer=3):
    return rf.record_evidence(store, ids, {"day": day, "field_id": field}, viewer)


# ---- reading ----------------------------------------------------------------------------------


def test_there_are_eight_tools_and_each_exists():
    assert len(TOOL_NAMES) == 8 and all(hasattr(Toolbox, name) for name in TOOL_NAMES)


def test_recall_lists_live_beliefs_and_can_filter(store):
    ids = rf.Ids()
    told(store, ids, 4)
    evidence(store, ids, 0, 0)
    box = toolbox(store)
    both = box.recall()
    assert "fire reaches F3 on day 4" in both and "fire reaches F0 on day 0" in both
    assert box.recall(subject="F0").count("\n") == 0 and "F3" not in box.recall(subject="F0")
    assert box.recall(subject="F5") == "nothing matches"


def test_recall_hides_stale_beliefs_unless_asked(store):
    ids = rf.Ids()
    told(store, ids, 4)
    store.expose("A3", "A2", tick=3)
    box = toolbox(store)
    assert box.recall() == "nothing matches"
    assert "stale" in box.recall(status="stale")


def test_explain_shows_route_sources_dependents_and_history(store):
    ids = rf.Ids()
    seen = evidence(store, ids, 0, 0)
    forecast = rf.forecast_arrival(store, ids, "A3", 3, tick=0)
    box = toolbox(store)
    assert f"derived from {seen.id} (active)" in box.explain(forecast.id)
    assert f"belief {forecast.id} (active) rests on it, 1 step(s) down" in box.explain(seen.id)
    told(store, ids, 4)
    store.expose("A3", "A2", tick=3, reason="evidence disagrees")
    (stale,) = store.beliefs("A3", status="stale")
    text = box.explain(stale.id)
    assert "tick 3: became stale because of exposure of A2 (evidence disagrees)" in text


def test_traverse_lists_entities_by_distance(store):
    assert (
        toolbox(store).traverse("F3", hops=2) == "0 step(s): F3\n1 step(s): F2 F4\n2 step(s): F1 F5"
    )
    assert toolbox(store).traverse("F3", hops=1).count("\n") == 1
    assert toolbox(store).traverse("nowhere").startswith("error: unknown entity")


def test_shortest_path_reports_a_cost_or_that_there_is_none(store):
    assert toolbox(store).shortest_path("F0", "F3") == "cost 3"
    assert toolbox(store).shortest_path("F0", "A1").startswith("no known path")


# ---- writing ----------------------------------------------------------------------------------


def test_assert_belief_records_a_derived_belief_that_depends_on_what_it_names(store):
    ids = rf.Ids()
    seen = evidence(store, ids, 0, 0)
    box = toolbox(store, ids)
    reply = box.assert_belief("F3", "fire.arrival_day", 3, depends_on=[seen.id], confidence=0.9)
    assert reply.startswith("recorded B")
    new_id = reply.split()[1]
    assert store.sources("A3", new_id) == [seen.id]
    assert store.get("A3", new_id).origin == "derived"
    assert new_id in store.dependents("A3", seen.id)


def test_assert_belief_warns_when_it_conflicts_with_something_already_believed(store):
    ids = rf.Ids()
    told(store, ids, 4)
    seen = evidence(store, ids, 0, 0)
    reply = toolbox(store, ids).assert_belief("F3", "fire.arrival_day", 3, depends_on=[seen.id])
    assert "note: conflicts with" in reply and "fire reaches F3 on day 4" in reply


@pytest.mark.parametrize(
    "call, message",
    [
        (dict(subject="F3", predicate="nope", value=1, depends_on=["B1"]), "unknown predicate"),
        (
            dict(subject="Z9", predicate="fire.arrival_day", value=1, depends_on=["B1"]),
            "unknown entity",
        ),
        (
            dict(subject="F3", predicate="fire.arrival_day", value=1, depends_on=[]),
            "depends_on is required",
        ),
        (
            dict(subject="F3", predicate="fire.arrival_day", value=1, depends_on=["B999"]),
            "not one of your beliefs",
        ),
        (
            dict(
                subject="F3", predicate="fire.arrival_day", value=1, depends_on=["B1"], confidence=2
            ),
            "confidence",
        ),
    ],
)
def test_assert_belief_refuses_a_bad_call_without_changing_anything(store, call, message):
    evidence(store, rf.Ids(), 0, 0)
    before = store.beliefs("A3")
    reply = toolbox(store).assert_belief(**call)
    assert reply.startswith("error:") and message in reply
    assert store.beliefs("A3") == before


def test_nothing_can_rest_on_a_belief_that_is_no_longer_sound(store):
    told(store, rf.Ids(), 4)
    store.expose("A3", "A2", tick=3)
    (stale,) = store.beliefs("A3", status="stale")
    reply = toolbox(store).assert_belief("F3", "fire.arrival_day", 4, depends_on=[stale.id])
    assert "no longer sound" in reply


def test_retract_withdraws_a_belief_and_flags_what_rests_on_it(store):
    ids = rf.Ids()
    seen = evidence(store, ids, 0, 0)
    forecast = rf.forecast_arrival(store, ids, "A3", 3, tick=0)
    reply = toolbox(store).retract(seen.id, "I misread it")
    assert reply == f"retracted {seen.id}; flagged for re-checking: {forecast.id}"
    assert store.get("A3", forecast.id).status == "suspect"
    assert toolbox(store).retract(seen.id).startswith("error:")  # already retracted
    assert toolbox(store, viewer="A4").retract(seen.id).startswith("error:")  # not A4's


# ---- reaching the game ------------------------------------------------------------------------


def test_send_hands_a_live_belief_to_the_transport(store):
    sent = []
    belief = told(store, rf.Ids(), 4)

    def transport(sender, receiver, b):
        sent.append((sender, receiver, b.id))
        return "sent"

    box = toolbox(store, transport=transport)
    assert box.send("A4", belief.id) == "sent" and sent == [("A3", "A4", belief.id)]
    store.expose("A3", "A2", tick=3)
    assert "do not pass it on" in box.send("A4", belief.id)  # it is stale now
    assert len(sent) == 1


def test_send_and_act_say_so_when_unavailable_or_refused(store):
    belief = told(store, rf.Ids(), 4)
    assert toolbox(store).send("A4", belief.id) == "error: sending is not available"

    def refuse(action):
        raise ValueError("you watered yesterday")

    box = toolbox(store, executor=refuse)
    assert box.act("water", "F3", depends_on=[belief.id]) == "error: you watered yesterday"
    assert store.actions("A3") == []  # a refused action leaves nothing behind


def test_act_records_a_commitment_that_is_flagged_if_its_basis_is_corrected(store):
    ids = rf.Ids()
    belief = told(store, ids, 4)
    box = toolbox(store, executor=lambda action: "will water")
    assert box.act("water", "F3", depends_on=[belief.id]) == "X1: will water"
    (action,) = store.actions("A3", status="committed")
    assert store.sources("A3", action.id) == [belief.id]
    store.expose("A3", "A2", tick=3)
    context = compile_context(store, "A3", 3, role_card="role", templates=rf.TEMPLATES)
    assert f"! depends on {belief.id}, which is stale" in context


def test_a_tool_never_raises_on_nonsense(store):
    box = toolbox(store)
    for call in (
        lambda: box.explain("nope"),
        lambda: box.retract("nope"),
        lambda: box.act("water", depends_on=["nope"]),
        lambda: box.send("A9", "nope"),
        lambda: box.assert_belief("F3", "fire.arrival_day", 1, depends_on=["nope"]),
    ):
        assert call().startswith("error:")


def test_every_store_gives_the_model_identical_tool_output(store):
    def run(s):
        ids = rf.Ids()
        told(s, ids, 4)
        seen = evidence(s, ids, 0, 0)
        box = toolbox(s, ids)
        out = [box.recall(), box.traverse("F3"), box.shortest_path("F0", "F3")]
        out.append(box.assert_belief("F3", "fire.arrival_day", 3, depends_on=[seen.id]))
        s.expose("A3", "A2", tick=3, reason="evidence disagrees")
        out += [box.recall(), box.recall(status="stale"), box.explain(seen.id)]
        out.append(box.retract(seen.id, "test"))
        return out

    reference = MemoryStore()
    rf.setup_map(reference, N, [(f, f) for f in range(N)], [(f, (f + 1) % N, 1) for f in range(N)])
    got, expected = run(store), run(reference)
    assert got == expected
    assert not any(line.startswith("error:") for line in got)  # it ran, not failed identically
