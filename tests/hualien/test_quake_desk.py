"""The Hualien quake on the frame: a hazard desk, a risk desk and fab ops, with a rumour."""

from graph_agent.frame.runtime import Item
from graph_agent.harness.llm import ModelReply, ScriptedModel
from graph_agent.packs.hualien.adapter import MAGNITUDE
from graph_agent.packs.hualien.run import build_quake, run_quake
from graph_agent.packs.hualien.standin import desk_team as stand_in
from graph_agent.packs.hualien.teams import desk_team
from graph_agent.packs.hualien.world import QUAKE, RUMOUR


def test_the_stand_in_desks_leave_every_fab_alerted_at_the_reviewed_level():
    run = run_quake(stand_in())
    assert all(run.checks.values()), run.checks
    assert run.world.in_force() == {"FabA": "medium", "FabB": "low", "FabC": "high"}
    assert run.score["unsafe_proposals"] == 0


def test_the_revision_holds_every_alert_built_on_the_early_figures():
    run = run_quake(stand_in())
    held = [e.data for e in run.runtime.log.events if e.kind == "held"]
    assert {h["arguments"]["fab"] for h in held} == {"FabA", "FabB", "FabC"}
    assert all("USGS revised it" in h["reason"] for h in held)
    # FabA was alerted high on the early figures, then medium once USGS revised them
    assert [a.level for a in run.world.alerts if a.fab == "FabA"] == ["high", "medium"]


def test_the_fabs_own_sensors_expose_the_rumour_and_no_agency_is_blamed():
    run = run_quake(stand_in())
    assert {v for v, a in run.runtime.exposed_pairs if a == RUMOUR} == {"hazard", "risk", "ops"}
    first = [e for e in run.runtime.exposures if e.agent == RUMOUR][0]
    assert first.viewer == "risk" and "FabA is running" in first.reason
    # an early figure that was later revised is not a lie
    assert run.score["honest_quarantined"] == 0


def test_an_early_figure_never_overwrites_a_reviewed_one():
    runtime, _ = build_quake(desk_team(), None)
    runtime.start()

    def report(item_id: str, source: str, magnitude: float, tick: int):
        claims = [(QUAKE, MAGNITUDE, magnitude)]
        item = Item(
            id=item_id, kind="report", tick=tick, source=source, about=[QUAKE], claims=claims
        )
        return runtime.route(item, ["hazard"])["hazard"][0]

    reviewed = report("x1", "USGS", 7.4, 0)
    report("x2", "PTWC", 7.5, 1)  # later, but less authoritative
    assert runtime.store.belief("hazard", reviewed.id).status == "active"
    early = report("x3", "ATWC", 7.6, 2)
    report("x4", "USGS", 7.4, 3)  # the reviewed figure again retires the early one
    assert runtime.store.belief("hazard", early.id).status == "retracted"


def test_a_desk_team_that_does_nothing_fails_the_checks():
    run = run_quake(ScriptedModel(lambda *a: ModelReply(text="done"), model="idle"))
    assert not all(run.checks.values())


def test_the_desk_runs_in_the_console(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from graph_agent.service.app import create_app

    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())
    team = client.get("/api/templates/hualien/desk").json()
    space = client.post("/api/spaces", json={"pack": "hualien", "team": team}).json()
    for _ in range(10):
        if client.post(f"/api/spaces/{space['id']}/step").json()["finished"]:
            break
    state = client.get(f"/api/spaces/{space['id']}").json()
    assert state["world"]["lens"] == "hualien"
    assert all(state["score"]["checks"].values())
    assert {f["id"]: f["alert"] for f in state["world"]["fabs"]} == {
        "FabA": "medium",
        "FabB": "low",
        "FabC": "high",
    }
