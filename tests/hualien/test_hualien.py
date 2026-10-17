"""The second domain: Hualien, 2024-04-02. Same core, same stores, nothing in core/ changed.

An early report (magnitude 7.5, depth 11 km) reaches the risk desk through a wire service and the
desk rates a nearby fab "high". USGS's reviewed solution (magnitude 7.4, depth 40 km, USGS event
us7000m9g4) arrives by another route. The desk must retract the early figures, learn that its
assessment rested on them, and rate the fab again.
"""

import pytest

from graph_agent.core.compiler import compile_context
from graph_agent.core.ids import Ids
from graph_agent.core.tools import Toolbox
from graph_agent.packs.hualien import adapter as hz
from stores_param import STORES

DESK = "RiskDesk"
AGENTS = ["USGS", "PTWC", "ATWC", "WireService", "NewsDesk", "HazardDesk", DESK]


@pytest.fixture(params=STORES)
def store(request):
    store = request.param()
    hz.setup(store, AGENTS, "Q1", {"FabA": 120, "FabB": 300})
    yield store
    store.close()


EARLY = {
    "route": ["PTWC", "WireService"],
    "receiver": DESK,
    "tick": 1,
    "quake": "Q1",
    "magnitude": 7.5,
    "depth_km": 11,
}
REVIEWED = {
    "route": ["USGS", "HazardDesk"],
    "receiver": DESK,
    "tick": 3,
    "quake": "Q1",
    "magnitude": 7.4,
    "depth_km": 40,
}


def value(store, predicate, status="active"):
    return sorted(b.value for b in store.beliefs(DESK, predicate=predicate, status=status))


# ---- the pieces -------------------------------------------------------------------------------


def test_a_report_becomes_beliefs_with_the_route_it_took(store):
    magnitude, depth = hz.record_report(store, Ids(), EARLY)
    assert (magnitude.value, depth.value) == (7.5, 11)
    assert store.support_routes(DESK, magnitude.id) == [("PTWC", "WireService")]


def test_the_same_figure_from_two_routes_is_one_belief_with_two_routes(store):
    ids = Ids()
    first, _ = hz.record_report(store, ids, EARLY)
    again, _ = hz.record_report(store, ids, {**EARLY, "route": ["ATWC", "NewsDesk"], "tick": 2})
    assert first.id == again.id
    assert len(store.support_routes(DESK, first.id)) == 2


def test_exposure_depends_on_how_strong_how_shallow_and_how_far(store):
    ids = Ids()
    hz.record_report(store, ids, EARLY)
    assert hz.assess_exposure(store, ids, DESK, "FabA", 1).value == "high"  # near and shallow
    assert hz.assess_exposure(store, ids, DESK, "FabB", 1).value == "low"  # 300 km away


def test_nothing_can_be_assessed_before_a_report_arrives(store):
    assert hz.assess_exposure(store, Ids(), DESK, "FabA", 1) is None


# ---- the story --------------------------------------------------------------------------------


def play(store):
    ids = Ids()
    hz.record_report(store, ids, EARLY)
    early_exposure = hz.assess_exposure(store, ids, DESK, "FabA", 1)
    new = hz.record_report(store, ids, REVIEWED)
    retracted = [r for belief in new for r in hz.retract_superseded(store, DESK, belief, 3)]
    return ids, early_exposure, retracted


def test_a_more_authoritative_revision_retracts_the_early_figures(store):
    _, _, retracted = play(store)
    assert len(retracted) == 2  # the early magnitude and the early depth
    assert value(store, hz.MAGNITUDE) == [7.4] and value(store, hz.MAGNITUDE, "retracted") == [7.5]
    assert value(store, hz.DEPTH) == [40] and value(store, hz.DEPTH, "retracted") == [11]


def test_the_assessment_that_rested_on_the_early_figures_is_flagged_not_silently_kept(store):
    _, early_exposure, _ = play(store)
    flagged = store.get(DESK, early_exposure.id)
    assert flagged.status == "suspect" and flagged.value == "high"
    changes = {c.belief_id: c for c in store.changes_since(DESK, 0)}
    assert changes[early_exposure.id].path_len == 2  # one step below a retracted figure


def test_the_desk_reassesses_and_the_new_rating_rests_on_the_reviewed_figures(store):
    ids, early_exposure, _ = play(store)
    fresh = hz.assess_exposure(store, ids, DESK, "FabA", 4)
    assert fresh.value == "medium"  # 7.4 at 40 km, 120 km away
    sources = store.sources(DESK, fresh.id)
    assert {store.get(DESK, s).value for s in sources} == {7.4, 40}
    assert store.get(DESK, early_exposure.id).status == "suspect"  # the old one is still flagged


def test_a_source_of_equal_authority_is_not_overruled_by_rule(store):
    ids = Ids()
    hz.record_report(store, ids, EARLY)  # PTWC says 7.5
    new = hz.record_report(store, ids, {**EARLY, "route": ["ATWC"], "tick": 2, "magnitude": 7.3})
    assert hz.retract_superseded(store, DESK, new[0], 2) == []
    assert value(store, hz.MAGNITUDE) == [7.3, 7.5]  # two live, disagreeing: the desk decides


def test_a_figure_within_tolerance_is_not_a_conflict(store):
    ids = Ids()
    hz.record_report(store, ids, EARLY)
    new = hz.record_report(store, ids, {**REVIEWED, "magnitude": 7.52, "depth_km": 12})
    assert hz.retract_superseded(store, DESK, new[0], 3) == []  # 7.52 vs 7.5, 12 vs 11


def test_an_unreliable_relay_can_be_distrusted_like_any_agent(store):
    """The other correction the core knows: exposing a relay removes support from what came
    through it. Here the wire service turns out to garble numbers."""
    ids = Ids()
    magnitude, _ = hz.record_report(store, ids, EARLY)
    exposure = hz.assess_exposure(store, ids, DESK, "FabA", 1)
    changes = store.expose(DESK, "WireService", tick=4, reason="published a wrong figure")
    assert store.get(DESK, magnitude.id).status == "stale"
    assert store.get(DESK, exposure.id).status == "suspect"
    assert {c.belief_id for c in changes} >= {magnitude.id, exposure.id}


# ---- what the desk is shown, and the tools it has ----------------------------------------------


def test_the_context_shows_the_revision_as_a_tombstone_with_the_flagged_assessment(store):
    ids, _, _ = play(store)
    hz.assess_exposure(store, ids, DESK, "FabA", 4)
    text = compile_context(
        store, DESK, since_tick=3, role_card=hz.role_card(DESK), templates=hz.TEMPLATES
    )
    assert "Q1 has magnitude 7.5" in text.split("## Changed since last turn")[1].split("##")[0]
    assert "[B1 RETRACTED]" in text and "FabA has high exposure" in text
    beliefs = text.split("## Beliefs")[1]
    assert "Q1 has magnitude 7.4" in beliefs and "Q1 has magnitude 7.5" not in beliefs


def test_the_same_eight_tools_work_in_this_domain(store):
    ids, early_exposure, _ = play(store)
    box = Toolbox(store, DESK, hz.PREDICATES, hz.TEMPLATES, ids)
    assert "FabA has high exposure" in box.explain(early_exposure.id)
    assert "retracted" in box.recall(status="retracted")
    reply = box.assert_belief(
        "FabA",
        hz.EXPOSURE,
        "medium",
        depends_on=[store.beliefs(DESK, predicate=hz.MAGNITUDE, status="active")[0].id],
    )
    assert reply.startswith("recorded")
    assert (
        box.shortest_path("Q1", "FabA") == "no known path from Q1 to FabA"
    )  # no map in this domain


def test_every_store_ends_in_the_same_state(store):
    from graph_agent.stores.memory import MemoryStore

    def story(s):
        ids = Ids()
        hz.record_report(s, ids, EARLY)
        hz.assess_exposure(s, ids, DESK, "FabA", 1)
        for belief in hz.record_report(s, ids, REVIEWED):
            hz.retract_superseded(s, DESK, belief, 3)
        hz.assess_exposure(s, ids, DESK, "FabA", 4)
        return [(b.id, b.status, b.value) for b in s.beliefs(DESK)], [
            c.model_dump() for c in s.changes_since(DESK, 0)
        ]

    reference = MemoryStore()
    hz.setup(reference, AGENTS, "Q1", {"FabA": 120, "FabB": 300})
    assert story(store) == story(reference)  # `store` was set up by the fixture
