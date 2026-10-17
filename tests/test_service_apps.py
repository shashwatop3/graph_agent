"""The "My apps" API: your connections and your agents, edited from the console."""

import json
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient  # noqa: E402

from graph_agent.frame import connections as frame_connections  # noqa: E402
from graph_agent.packs.apps.console import APPS  # noqa: E402
from graph_agent.packs.life.mcp_server import life_server  # noqa: E402
from graph_agent.packs.life.world import LifeWorld  # noqa: E402
from graph_agent.service import connections as api  # noqa: E402
from graph_agent.service.app import create_app  # noqa: E402

LOCAL = "http://127.0.0.1:8765"


@pytest.fixture
def files(tmp_path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(api, "CONNECTIONS", tmp_path / "connections.json")
    monkeypatch.setattr(api, "ROOT", tmp_path)  # no .env
    monkeypatch.setattr(APPS, "agents_file", tmp_path / "agents.json")
    monkeypatch.setattr(APPS, "connections_file", tmp_path / "connections.json")
    monkeypatch.delenv("TODOIST_API_KEY", raising=False)
    return tmp_path


@pytest.fixture
def client(files) -> TestClient:  # noqa: ANN001
    return TestClient(create_app(), base_url=LOCAL)


def test_presets_and_your_connections_with_what_each_still_needs(client: TestClient):
    first = client.get("/api/connections").json()
    assert {p["name"] for p in first["presets"]} == {"google", "todoist"}
    assert first["connections"] == []
    saved = client.put("/api/connections", json={"connections": [{"preset": "todoist"}]})
    assert saved.status_code == 200
    (todoist,) = saved.json()["connections"]
    assert todoist["missing"] == ["TODOIST_API_KEY"]
    assert client.get("/api/connections").json()["entries"] == [{"preset": "todoist"}]


def test_a_bad_connection_is_refused_with_the_reason(client: TestClient):
    bad = client.put("/api/connections", json={"connections": [{"name": "x"}]})
    assert bad.status_code == 400 and "either a command or a url" in bad.json()["detail"]


def test_only_this_console_on_this_machine_may_write_or_start_servers(files):  # noqa: ANN001
    body = {"connections": [{"name": "evil", "command": "rm", "args": ["-rf", "/"]}]}
    other_site = TestClient(create_app(), base_url=LOCAL, headers={"origin": "https://x.example"})
    assert other_site.put("/api/connections", json=body).status_code == 403
    assert other_site.post("/api/connections/test", json=body["connections"][0]).status_code == 403
    rebound = TestClient(create_app(), base_url="http://evil.example:8765")
    assert rebound.put("/api/connections", json=body).status_code == 403
    assert not (files / "connections.json").exists()
    same = TestClient(create_app(), base_url=LOCAL, headers={"origin": LOCAL})
    ok = same.put("/api/connections", json={"connections": [{"preset": "todoist"}]})
    assert ok.status_code == 200


def test_testing_a_connection_lists_its_tools_and_reads_its_feeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    real = frame_connections.connect
    monkeypatch.setattr(api, "connect", lambda c: real(c, server=life_server(LifeWorld())))
    entry: dict[str, Any] = {
        "name": "sim",
        "command": "unused",
        "include": ["mail_*"],
        "feeds": [{"name": "mail", "tool": "mail_search", "args": {"query": ""}, "ids": "(m\\d+)"}],
    }
    found = client.post("/api/connections/test", json=entry).json()
    assert found["ok"]
    assert {t["name"]: t["outward"] for t in found["tools"]} == {
        "sim_mail_search": False,
        "sim_mail_read": False,
        "sim_mail_send": True,
    }
    assert found["feeds"] == [{"name": "mail", "items": 0, "sample": []}]
    missing = client.post("/api/connections/test", json={"preset": "todoist"}).json()
    assert missing == {"ok": False, "error": "set TODOIST_API_KEY in .env"}


def test_the_agents_form_round_trip(client: TestClient, files):  # noqa: ANN001
    view = client.get("/api/packs/apps/setup").json()
    assert not view["saved"] and [a["name"] for a in view["setup"]["agents"]][0] == "inbox"
    assert "Promise" in view["kinds"]
    bad = {"agents": [{"name": "Tasks", "job": "x"}]}
    assert client.post("/api/packs/apps/setup/check", json=bad).json()["problems"] == [
        "agent 'Tasks': use a short lowercase name (letters, digits, -)"
    ]
    assert not (files / "agents.json").exists()  # checking writes nothing
    good = {"name": "Mine", "agents": [{"name": "inbox", "job": "Read my mail."}]}
    assert client.put("/api/packs/apps/setup", json=good).json()["problems"] == []
    assert json.loads((files / "agents.json").read_text())["name"] == "Mine"
    names = {(t["pack"], t["name"]) for t in client.get("/api/templates").json()}
    assert ("apps", "mine") in names and ("apps", "example") in names
    unparsable = client.post("/api/packs/apps/setup/check", json={"agents": [{"name": "x"}]})
    assert unparsable.json()["problems"] == ["agents.0.job: Field required"]
    assert client.get("/api/packs/life/setup").status_code == 404


def test_your_agents_need_a_real_model(client: TestClient):
    team = client.get("/api/templates/apps/example").json()
    made = client.post("/api/spaces", json={"pack": "apps", "team": team, "model": "stand-in"})
    assert made.status_code == 400 and "need a real model" in made.json()["detail"]
