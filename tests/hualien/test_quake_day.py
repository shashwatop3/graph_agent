"""The Hualien day: three real quakes from five sources, matched to their quakes, and four posts."""

import json
from pathlib import Path

from graph_agent.packs.hualien.run import run_quake
from graph_agent.packs.hualien.snapshot import day_graph
from graph_agent.packs.hualien.standin import desk_team as stand_in
from graph_agent.packs.hualien.teams import day_team
from graph_agent.packs.hualien.world import DAY, RUMOUR, QuakeWorld, Reading, quake_name

MAIN, FIRST, SECOND = "q-2024-04-02T2358", "q-2024-04-03T0011", "q-2024-04-03T0035"


def _replay() -> QuakeWorld:
    world = QuakeWorld(script="day")
    for tick in range(11):
        for feed in ("centres", "usgs", "emsc", "gdacs", "posts"):
            world.reports_due(tick, feed)
    return world


def test_every_agency_report_is_matched_to_its_own_quake():
    world = _replay()
    assert {k.id: len(k.reports) for k in world.known} == {MAIN: 5, FIRST: 2, SECOND: 2}
    # the second aftershock is 6 km from the first, but 24 minutes later: another quake
    assert any(m["quake"] == SECOND and "a new quake: 24 min" in m["why"] for m in world.matched)


def test_naming_by_region_and_date_would_make_two_quakes_of_one_day_the_same():
    readings = [r for r in DAY if isinstance(r, Reading) and r.source == "USGS"]
    by_date = {r.origin[:10] for r in readings}  # all three are in Hualien
    assert len(by_date) < len(readings)  # the old rule (q-<region>-<date>) merges them
    assert len({quake_name(r.origin) for r in readings}) == len(readings)


def test_a_post_is_matched_by_the_magnitude_it_names():
    world = _replay()
    about = {
        m["report"].split()[1]: m["quake"] for m in world.matched if m["report"].startswith("post")
    }
    assert about == {"p1": MAIN, "p2": MAIN, "p3": FIRST}  # p4, a joke, names no quake


def test_the_stand_in_desk_passes_every_check():
    run = run_quake(stand_in(), team=day_team())
    assert all(run.checks.values()), run.checks
    assert run.score["unsafe_proposals"] == 0


def test_the_review_reaches_exactly_what_rested_on_the_early_figures():
    run = run_quake(stand_in(), team=day_team())
    held = [e.data["arguments"] for e in run.runtime.log.events if e.kind == "held"]
    # the main shock's bulletin and the three fab alerts, never an aftershock's bulletin
    assert {h.get("quake") for h in held if "quake" in h} == {MAIN}
    assert {h["fab"] for h in held if "fab" in h} == {"FabA", "FabB", "FabC"}
    assert [b.text for b in run.world.bulletins if b.quake == MAIN] == [
        "M7.5, 11.4 km deep, tsunami: yes",
        "M7.4, 40 km deep, tsunami: yes",
    ]


def test_only_the_lying_account_is_distrusted():
    run = run_quake(stand_in(), team=day_team())
    assert {a for _, a in run.runtime.exposed_pairs} == {RUMOUR}
    # the honest posters, and the agencies whose early figures were revised, are trusted
    assert run.score["honest_quarantined"] == 0


def test_the_day_runs_in_the_console(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from graph_agent.service.app import create_app

    monkeypatch.chdir(tmp_path)
    client = TestClient(create_app())
    team = client.get("/api/templates/hualien/day").json()
    space = client.post("/api/spaces", json={"pack": "hualien", "team": team}).json()
    for _ in range(14):
        if client.post(f"/api/spaces/{space['id']}/step").json()["finished"]:
            break
    state = client.get(f"/api/spaces/{space['id']}").json()
    assert all(state["score"]["checks"].values())
    assert [q["id"] for q in state["world"]["quakes"]] == [MAIN, FIRST, SECOND]
    assert state["world"]["quakes"][0]["bulletin"] == "M7.4, 40 km deep, tsunami: yes"


def test_the_setup_pages_drawing_is_what_a_run_gives():
    """viewer/console/src/setups/quakeDay.json is made by `python -m ...hualien.snapshot`."""
    drawn = Path(__file__).parents[2] / "viewer/console/src/setups/quakeDay.json"
    assert json.loads(drawn.read_text()) == json.loads(json.dumps(day_graph()))
