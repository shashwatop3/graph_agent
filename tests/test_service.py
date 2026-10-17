"""The HTTP API the console uses: templates, the catalogue, spaces that run a team, why-chains and
approvals. Uses the stand-in models, so it costs nothing."""

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from graph_agent.service.app import create_app  # noqa: E402


@pytest.fixture
def client():
    return TestClient(create_app())


def run_to_end(client, space_id):
    for _ in range(20):
        summary = client.post(f"/api/spaces/{space_id}/step").json()
        if summary["finished"]:
            return summary
    raise AssertionError("never finished")


def test_the_page_can_load_any_listed_pack(client):
    packs = {p["name"]: p for p in client.get("/api/packs").json()}
    assert set(packs) == {"life", "offsite", "ringfire", "hualien"}
    assert {o["key"] for o in packs["life"]["options"]} == {"approvals", "extraction", "week"}
    assert packs["ringfire"]["options"] == []
    nodes = {
        n["type"] for n in client.get("/api/catalogue", params={"pack": "ringfire"}).json()["nodes"]
    }
    assert "ringfire.world" in nodes and "agent" in nodes
    assert client.get("/api/catalogue", params={"pack": "nope"}).status_code == 404


def test_templates_and_the_catalogue(client):
    names = {(t["pack"], t["name"]) for t in client.get("/api/templates").json()}
    assert ("life", "week") in names and ("ringfire", "ringfire") in names
    catalogue = client.get("/api/catalogue", params={"pack": "life"}).json()
    tools = {t["name"]: t for t in catalogue["tools"]}
    assert tools["bank_pay"]["outward"] and tools["flight_status"]["checking"]
    assert "responder" in {n["type"] for n in catalogue["nodes"]}
    assert set(catalogue["links"]) == {"feeds", "owns", "talks_to", "watches"}
    team = client.get("/api/templates/life/travel").json()
    assert client.post("/api/validate", json=team).json() == {"ok": True, "errors": []}
    team["links"].append({"kind": "talks_to", "src": "travel", "dst": "nobody"})
    assert not client.post("/api/validate", json=team).json()["ok"]


def test_a_life_space_runs_and_explains_itself(client):
    team = client.get("/api/templates/life/travel").json()
    space = client.post("/api/spaces", json={"pack": "life", "team": team, "name": "travel"}).json()
    summary = run_to_end(client, space["id"])
    assert summary["tick"] == 14
    state = client.get(f"/api/spaces/{space['id']}").json()
    assert all(state["score"]["checks"].values())
    assert {o["id"] for o in state["outside"]} >= {"support@skyways-verify.example"}
    scam = [o for o in state["outside"] if o["id"] == "support@skyways-verify.example"][0]
    assert set(scam["quarantined_by"]) == {"inbox", "travel", "calendar", "actions"}
    plan = [
        b
        for b in state["beliefs"]["actions"]
        if b["predicate"] == "plan.cab_pickup" and b["status"] == "retracted"
    ][0]
    why = client.get(f"/api/spaces/{space['id']}/why/actions/{plan['id']}").json()
    assert why["upstream"][0]["sender"] == "travel"
    assert why["changes"] and why["actions"]  # it was withdrawn, and an action rested on it
    assert "MATCH" in why["cypher"]["routes"]
    events = client.get(f"/api/spaces/{space['id']}/events", params={"since": 0}).json()
    assert events[0]["kind"] == "run_start" and events[-1]["kind"] == "run_end"


def test_outward_actions_wait_for_a_person(client):
    team = client.get("/api/templates/life/money").json()
    space = client.post(
        "/api/spaces",
        json={"pack": "life", "team": team, "name": "money", "options": {"approvals": "manual"}},
    ).json()
    for _ in range(3):
        client.post(f"/api/spaces/{space['id']}/step")
    pending = [
        p
        for p in client.get(f"/api/spaces/{space['id']}").json()["proposals"]
        if p["status"] == "pending"
    ]
    assert pending and all(p["tool"] == "subscription_set_card" for p in pending)
    answer = client.post(
        f"/api/spaces/{space['id']}/approvals/{pending[0]['id']}", json={"approved": True}
    ).json()
    assert "charged to card-5555" in answer["result"]
    rejected = client.post(
        f"/api/spaces/{space['id']}/approvals/{pending[1]['id']}", json={"approved": False}
    ).json()
    assert rejected["result"].endswith("rejected")


def test_a_ringfire_space(client):
    team = client.post(
        "/api/templates/ringfire/ringfire", json={"n_agents": 6, "imposters": 1}
    ).json()
    space = client.post("/api/spaces", json={"pack": "ringfire", "team": team}).json()
    summary = run_to_end(client, space["id"])
    state = client.get(f"/api/spaces/{space['id']}").json()
    assert summary["finished"] and state["world"]["lens"] == "ringfire"
    assert state["score"]["fields"] == 6


def test_the_real_accounts_team_is_offered_and_says_what_is_missing(client, monkeypatch):
    for name in (
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_CLIENT_API",
        "USER_GOOGLE_EMAIL",
        "TODOIST_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("graph_agent.packs.life.real.load_env", lambda: None)
    assert ("life", "real") in {(t["pack"], t["name"]) for t in client.get("/api/templates").json()}
    team = client.get("/api/templates/life/real").json()
    assert team["settings"]["approvals"] == "shadow"  # never runs an action by default
    answer = client.post("/api/spaces", json={"pack": "life", "team": team})
    assert answer.status_code == 400 and "USER_GOOGLE_EMAIL" in answer.json()["detail"]
    approvals = {o["key"]: o for o in client.get("/api/packs").json()[0]["options"]}["approvals"]
    assert "shadow" in {c["value"] for c in approvals["choices"]}
