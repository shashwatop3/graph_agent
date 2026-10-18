"""A team of your own agents that reads live public data (streams) besides, or instead of, your
apps: its streams become stream nodes like the feeds', their items routed and read the same way.
The pages here are the test's own; nothing goes on the internet."""

import json
from typing import Any

import pytest

pytest.importorskip("mcp")

from graph_agent.frame.streams import LiveStream, Stream, stream_of  # noqa: E402
from graph_agent.harness.llm import ChatMessage, ModelReply, ScriptedModel  # noqa: E402
from graph_agent.packs.apps.console import AppsConsole  # noqa: E402
from graph_agent.packs.apps.pack import EXTRACT_PROMPT  # noqa: E402
from graph_agent.packs.apps.public_streams import PUBLIC, TOPICS  # noqa: E402
from graph_agent.packs.apps.run import build_apps  # noqa: E402
from graph_agent.packs.apps.setup import Setup, problems, team_of  # noqa: E402
from graph_agent.stores.memory import MemoryStore  # noqa: E402

DESK = {
    "name": "Quake desk",
    "agents": [
        {"name": "seismic", "job": "Keep each quake's magnitude.", "looks_after": ["Quake"]},
        {"name": "rumours", "job": "Read what people say about quakes."},
    ],
    "things": {"Quake": ["magnitude", "place"]},
    "streams": [
        {"preset": "usgs-quakes"},
        {"preset": "bluesky-posts", "keep": {"commit.record.text": "(?i)quake"}},
    ],
}


def desk(**changes: Any) -> Setup:
    return Setup.model_validate({**DESK, **changes})


def test_a_preset_with_your_filter_added_to_its_own():
    posts = stream_of({"preset": "bluesky-posts", "keep": {"commit.record.text": "quake"}}, PUBLIC)
    assert posts.name == "bluesky-posts" and posts.kind == "websocket"
    assert posts.keep == {"commit.operation": "^create$", "commit.record.text": "quake"}
    renamed = stream_of({"preset": "usgs-quakes", "name": "usgs", "most": 3}, PUBLIC)
    assert (renamed.name, renamed.most, renamed.trusted) == ("usgs", 3, True)
    with pytest.raises(ValueError, match="no stream 'nope'"):
        stream_of({"preset": "nope"}, PUBLIC)


def test_every_public_stream_is_valid_and_in_one_topic():
    listed = [name for names in TOPICS.values() for name in names]
    assert sorted(listed) == sorted(PUBLIC)
    for name in PUBLIC:
        stream = stream_of({"preset": name}, PUBLIC)
        assert stream.label and stream.about, name
        assert stream.kind != "poll" or stream.id, f"{name}: a page polled needs an id"


def test_streams_become_stream_nodes_that_feed_the_router():
    team = team_of(desk(), [])
    streams = {n.id: (n.type, n.label, n.config) for n in team.nodes if n.type == "stream"}
    assert streams == {
        "usgs-quakes-feed": (
            "stream",
            "USGS: earthquakes, magnitude 4.5 and up",
            {"feed": "usgs-quakes"},
        ),
        "bluesky-posts-feed": ("stream", "Bluesky: public posts", {"feed": "bluesky-posts"}),
    }  # fmt: skip
    links = {(link.kind, link.src, link.dst) for link in team.links}
    assert ("feeds", "usgs-quakes-feed", "router") in links
    assert team.settings.pace == 30  # a poll every 30 seconds: 24 polls watch for 12 minutes
    assert team.settings.extra["streams"] == DESK["streams"]  # they go with the team
    assert team.description == "2 agents on usgs-quakes, bluesky-posts"
    assert team_of(desk(pace=5), []).settings.pace == 5
    assert "streams" not in team_of(desk(streams=[]), []).settings.extra
    assert team_of(desk(streams=[]), []).settings.pace == 0  # no live data: no waiting


def test_what_is_wrong_with_a_stream_is_said_in_words():
    assert problems(desk(), []) == []
    assert problems(desk(streams=[{"preset": "nope"}]), []) == [
        "stream nope: no stream 'nope'; the streams are " + ", ".join(sorted(PUBLIC))
    ]
    bad_regex = [{"preset": "usgs-quakes", "keep": {"properties.place": "(Taiwan"}}]
    (wrong,) = problems(desk(streams=bad_regex), [])
    assert wrong.startswith("stream usgs-quakes: ") and "is not a regex" in wrong
    no_url = [{"name": "mine", "kind": "poll"}]
    assert problems(desk(streams=no_url), []) == ["stream mine: url: Field required"]
    twice = [{"preset": "usgs-quakes"}, {"preset": "usgs-quakes"}]
    assert problems(desk(streams=twice), []) == [
        "two feeds or streams are named 'usgs-quakes': rename one (\"name\": ...)"
    ]
    taken = desk(agents=[{"name": "usgs-quakes-feed", "job": "x"}])
    assert "agent 'usgs-quakes-feed': that name is taken; pick another" in problems(taken, [])


USGS = {
    "features": [
        {
            "id": "us7000abcd",
            "properties": {
                "title": "M 6.1 - 20 km E of Hualien City, Taiwan",
                "mag": 6.1,
                "place": "20 km E of Hualien City, Taiwan",
                "time": 1792300467356,
                "status": "automatic",
            },
        }
    ]
}


def extractor() -> ScriptedModel:
    """Reads a USGS item into the quake's magnitude; the agents only say they are done."""

    def policy(system: str, messages: list[ChatMessage], tools: list[Any]) -> ModelReply:
        if system == EXTRACT_PROMPT:
            text = str(messages[-1]["content"])
            if "properties.mag: 6.1" in text:
                return ModelReply(
                    text=json.dumps(
                        {
                            "new_entities": [["q-hualien", "Quake", "Hualien quake"]],
                            "about": ["q-hualien"],
                            "claims": [["q-hualien", "quake.magnitude", 6.1]],
                        }
                    )
                )
            return ModelReply(text="{}")
        return ModelReply(text="done")

    return ScriptedModel(policy, model="streams-test")


def test_a_stream_item_reaches_the_owner_as_evidence_from_a_trusted_stream():
    pages: list[str] = []

    def page(url: str, headers: dict[str, str]) -> str:
        pages.append(url)
        return json.dumps(USGS)

    setup = desk(streams=[{"preset": "usgs-quakes"}])
    rt, pack = build_apps(team_of(setup, []), [], extractor(), MemoryStore(), pages=page)
    try:
        assert isinstance(rt.feeds["usgs-quakes"], LiveStream)
        rt.start()
        rt.step()
        rt.step()  # read once: `every` seconds have not gone
    finally:
        rt.close()
    assert len(pages) == 1 and "4.5_day.geojson" in pages[0]
    items = [e for e in rt.log.events if e.kind == "item"]
    assert [e.data["source"] for e in items] == ["usgs-quakes"]
    assert rt.owners("q-hualien") == ["seismic"]  # the router sends it to who looks after quakes
    (belief,) = rt.store.beliefs("seismic", predicate="quake.magnitude")
    assert belief.value == 6.1
    assert belief.origin == "observed"  # a trusted stream: its items are evidence
    assert "usgs-quakes" in pack.observed_sources


def test_a_stream_this_console_may_not_read_stops_the_run_before_it_starts():
    def allow(stream: Stream) -> None:
        if "usgs" in stream.url:
            raise ValueError(f"stream {stream.name}: not here")

    setup = desk(streams=[{"preset": "usgs-quakes"}])
    with pytest.raises(ValueError, match="stream usgs-quakes: not here"):
        build_apps(team_of(setup, []), [], extractor(), MemoryStore(), allow=allow)


def test_the_console_names_a_forbidden_stream_among_the_problems(tmp_path: Any):
    def allow(stream: Stream) -> None:
        if stream.kind == "websocket":
            raise ValueError(f"stream {stream.name}: no websockets here")

    console = AppsConsole(
        tmp_path / "teams", tmp_path / "connections.json", lambda: {}, allow=allow
    )
    saved = console.save_setup(DESK)
    assert saved["problems"] == ["stream bluesky-posts: no websockets here"]
    assert console.setup_view(saved["team"])["problems"] == saved["problems"]
