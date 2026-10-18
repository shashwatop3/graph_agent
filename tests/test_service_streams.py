"""The console's streams: the public ones offered by topic, a peek at one, what a hosted console
refuses, and a team with live data played at its own pace. No page is read off the internet."""

import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient  # noqa: E402

from graph_agent.frame import streams  # noqa: E402
from graph_agent.packs.apps.public_streams import PUBLIC, TOPICS  # noqa: E402
from graph_agent.service.app import create_app  # noqa: E402
from graph_agent.service.registry import pack_named  # noqa: E402
from graph_agent.service.spaces import Spaces  # noqa: E402
from test_service_auth import hosted, signed_in  # noqa: E402, F401

LOCAL = "http://127.0.0.1:8765"
QUAKES = {"features": [{"id": "q1", "properties": {"title": "M 6.1 - Hualien", "mag": 6.1}}]}


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every page a stream reads is QUAKES; the list says which were asked for."""
    asked: list[str] = []

    def read(url: str, headers: dict[str, str]) -> str:
        asked.append(url)
        return json.dumps(QUAKES)

    monkeypatch.setattr(streams, "read_page", read)
    return asked


def local() -> TestClient:
    return TestClient(create_app(), base_url=LOCAL)


def test_the_public_streams_are_offered_by_topic():
    topics = local().get("/api/streams").json()["topics"]
    assert [t["topic"] for t in topics] == list(TOPICS)
    shown = {s["name"]: s for t in topics for s in t["streams"]}
    assert sorted(shown) == sorted(PUBLIC)
    usgs = shown["usgs-quakes"]
    assert usgs["kind"] == "poll" and usgs["trusted"] is True
    assert usgs["url"].startswith("https://earthquake.usgs.gov/")
    assert shown["bluesky-posts"]["keep"] == {"commit.operation": "^create$"}


def test_a_peek_shows_what_the_team_would_get(pages: list[str]):
    entry = {"preset": "usgs-quakes", "keep": {"properties.title": "Hualien"}}
    answer = local().post("/api/streams/peek", json=entry).json()
    assert answer["received"] == 1 and answer["kept"] == 1 and answer["error"] == ""
    (item,) = answer["items"]
    assert item["from"] == "usgs-quakes" and item["subject"] == "M 6.1 - Hualien"
    assert "properties.mag: 6.1" in item["body"]
    assert len(pages) == 1


def test_a_peek_at_a_stream_that_is_not_valid_says_why():
    answer = local().post("/api/streams/peek", json={"name": "mine", "url": "ftp://x.example"})
    assert answer.status_code == 400
    assert answer.json()["detail"] == "stream mine: a poll url starts with https://"


def test_a_peek_comes_only_from_the_console_on_this_machine(pages: list[str]):
    client = TestClient(create_app(), base_url=LOCAL, headers={"origin": "https://evil.example"})
    assert client.post("/api/streams/peek", json={"preset": "usgs-quakes"}).status_code == 403
    assert pages == []


def test_hosted_a_stream_must_be_on_the_public_internet(hosted, pages: list[str]):  # noqa: ANN001, F811
    client = signed_in()
    inside = {"name": "metadata", "url": "https://127.0.0.1/latest/meta-data"}
    answer = client.post("/api/streams/peek", json=inside)
    assert answer.status_code == 400
    assert answer.json()["detail"] == "stream metadata: 127.0.0.1 is not on the public internet"
    socket = {"name": "plain", "kind": "websocket", "url": "ws://stream.example/"}
    answer = client.post("/api/streams/peek", json=socket)
    assert answer.json()["detail"] == "stream plain: the url must start with wss://"
    assert pages == []


def test_hosted_a_team_with_a_stream_inside_cannot_run(hosted):  # noqa: ANN001, F811
    client = signed_in()
    setup = {
        "name": "Sneaky",
        "agents": [{"name": "reader", "job": "Read it."}],
        "streams": [{"name": "inside", "url": "https://10.0.0.8/admin"}],
    }
    saved = client.put("/api/packs/apps/setup", json=setup).json()
    assert saved["problems"] == ["stream inside: 10.0.0.8 is not on the public internet"]
    team = client.get(f"/api/templates/apps/{saved['team']}").json()
    run = client.post("/api/spaces", json={"pack": "apps", "team": team, "model": "stand-in"})
    assert run.status_code == 400


def test_a_team_with_live_data_is_played_at_its_pace():
    pack = pack_named("life")
    team = pack.team(pack.templates()[0].name, {})
    team.settings.pace = 0.6
    space = Spaces().create(pack, team, model="stand-in")
    try:
        space.play()  # the page's own delay is smaller: the team's pace wins
        time.sleep(1.0)
        assert space.runtime.tick == 2  # one at once, one 0.6 s later
        space.pause()
        space.play()  # paused and played again: one loop goes on, not two
        time.sleep(0.3)
        assert space.running
    finally:
        space.pause()
        space.runtime.close()
