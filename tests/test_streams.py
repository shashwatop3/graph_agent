"""Streams: live public data (a page, a websocket, an event stream) read into items, offline: the
servers here are local ones, and a page is whatever the test says it is."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

pytest.importorskip("websockets")

from websockets.sync.server import ServerConnection, serve  # noqa: E402

from graph_agent.frame.streams import (  # noqa: E402
    LiveStream,
    Stream,
    at,
    peek,
    rss_items,
    shown,
)

QUAKES = {
    "name": "quakes",
    "url": "https://example.org/quakes.json",
    "items": "features",
    "id": "id",
    "title": "properties.title",
    "fields": ["properties.mag", "properties.time|ms", "properties.status"],
    "most": 2,
}


def quake(qid: str, mag: float, status: str = "automatic") -> dict[str, Any]:
    title = f"M {mag} - somewhere"
    return {
        "id": qid,
        "properties": {"mag": mag, "time": 1792300467356, "status": status, "title": title},
    }


class Pages:
    """The page a poll reads: whatever was put here last."""

    def __init__(self) -> None:
        self.page = ""
        self.asked: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> str:
        self.asked.append((url, headers))
        return self.page

    def put(self, *features: dict[str, Any]) -> None:
        self.page = json.dumps({"features": list(features)})


def polled(stream: LiveStream, tick: int = 0) -> list[Any]:
    stream.read_at = 0  # as if `every` seconds had gone
    return stream(tick)


def test_paths_reach_into_dicts_and_lists():
    data = {"a": {"b": [{"c": 1}, {"c": 2}]}}
    assert at(data, "a.b.1.c") == 2
    assert at(data, "a.x.c") is None and at(data, "a.b.9") is None
    assert at(data, None) is data
    assert shown({"t": 1792300467356}, "t|ms") == ("t", "2026-10-18T05:14:27+00:00")
    assert shown({"t": 1792300467}, "t|s") == ("t", "2026-10-18T05:14:27+00:00")
    assert shown({"x": [1, 2]}, "x") == ("x", "[1, 2]")


def test_a_poll_gives_the_newest_oldest_first_then_only_what_is_new_or_changed():
    pages = Pages()
    live = LiveStream(Stream.model_validate(QUAKES), get=pages)
    pages.put(quake("c", 5.1), quake("b", 4.8), quake("a", 4.6))  # newest first
    first = polled(live)
    assert [i.id.split("-")[1] for i in first] == ["b", "c"]  # at most 2: the newest, in order
    assert live.skipped == 1
    item = first[1]
    assert item.source == "quakes" and item.kind == "quakes"
    assert item.payload["subject"] == "M 5.1 - somewhere"
    assert item.payload["body"] == (
        "properties.mag: 5.1\nproperties.time: 2026-10-18T05:14:27+00:00\n"
        "properties.status: automatic"
    )
    assert polled(live) == []  # the same page: nothing new
    pages.put(quake("c", 5.3, "reviewed"), quake("b", 4.8), quake("a", 4.6))
    (update,) = polled(live)  # c revised: it comes again, as an update with its own id
    assert "5.3" in update.payload["body"] and update.id != item.id
    assert live(5) == []  # `every` seconds have not gone: not read
    assert len(pages.asked) == 3
    assert pages.asked[0][1]["User-Agent"].startswith("groundwork")


def test_keep_and_drop_filter_items_and_the_counts_say_so():
    pages = Pages()
    spec = {**QUAKES, "most": 5, "keep": {"properties.mag": r"^[5-9]"}, "drop": {"id": "^x"}}
    live = LiveStream(Stream.model_validate(spec), get=pages)
    pages.put(quake("a", 5.5), quake("b", 4.1), quake("x1", 6.0))
    items = polled(live)
    assert [i.id.split("-")[1] for i in items] == ["a"]
    assert (live.received, live.kept) == (3, 1)


def test_a_sender_is_the_source_and_secrets_fill_the_url_and_headers():
    pages = Pages()
    spec = {
        "name": "posts",
        "url": "https://example.org/$FEED_PATH",
        "headers": {"Authorization": "Bearer $FEED_TOKEN"},
        "sender": "author",
        "id": "id",
    }
    live = LiveStream(Stream.model_validate(spec), {"FEED_PATH": "p", "FEED_TOKEN": "t"}, pages)
    pages.page = json.dumps([{"id": 1, "author": "Ann", "text": "hi"}])
    (item,) = polled(live)
    assert item.source == "ann" and item.payload["from"] == "ann"
    assert json.loads(item.payload["body"]) == {"author": "Ann", "id": 1, "text": "hi"}
    url, headers = pages.asked[0]
    assert url == "https://example.org/p" and headers["Authorization"] == "Bearer t"


def test_a_page_that_fails_is_an_error_not_a_crash():
    def broken(url: str, headers: dict[str, str]) -> str:
        return "<html>not json"

    live = LiveStream(Stream.model_validate(QUAKES), get=broken)
    assert polled(live) == []
    assert live.error.startswith("JSONDecodeError")


RSS = """﻿<?xml version="1.0"?>
<rss version="2.0" xmlns:gdacs="http://www.gdacs.org"><channel><title>t</title>
<item><title>Red earthquake in Taiwan</title><guid>EQ2</guid>
  <gdacs:alertlevel>Red</gdacs:alertlevel>
  <gdacs:severity unit="M" value="7.4">M 7.4</gdacs:severity>
</item>
<item><title>Green flood in Chad</title><guid>FL1</guid><gdacs:alertlevel>Green</gdacs:alertlevel>
</item></channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>A</title><id>1</id>
<link href="https://example.org/a"/></entry></feed>"""


def test_rss_and_atom_items_are_their_tags():
    first, second = rss_items(RSS)
    assert first == {"title": "Red earthquake in Taiwan", "guid": "EQ2", "alertlevel": "Red",
                     "severity": "M 7.4"}  # fmt: skip
    assert second["alertlevel"] == "Green"
    assert rss_items(ATOM) == [{"title": "A", "id": "1", "link": "https://example.org/a"}]
    spec = {"name": "alerts", "url": "https://example.org/rss", "format": "rss", "id": "guid",
            "title": "title", "keep": {"alertlevel": "Red|Orange"}}  # fmt: skip
    live = LiveStream(Stream.model_validate(spec), get=lambda url, headers: RSS)
    (item,) = polled(live)
    assert item.payload["subject"] == "Red earthquake in Taiwan"


def test_a_stream_is_checked_when_it_is_made():
    with pytest.raises(ValueError, match="starts with wss://"):
        Stream.model_validate({"name": "s", "kind": "websocket", "url": "https://x.org"})
    with pytest.raises(ValueError, match="starts with https://"):
        Stream.model_validate({"name": "s", "url": "file:///etc/passwd"})
    with pytest.raises(ValueError, match="not a regex"):
        Stream.model_validate({"name": "s", "url": "https://x.org", "keep": {"a": "("}})
    with pytest.raises(ValueError, match="lowercase"):
        Stream.model_validate({"name": "Quakes!", "url": "https://x.org"})
    with pytest.raises(ValueError, match="greater than or equal to 10"):
        Stream.model_validate({"name": "s", "url": "https://x.org", "every": 1})


# ---- websockets and event streams, from servers on this machine --------------------------------


@pytest.fixture
def socket_server():
    """A websocket server that answers a hello with three messages, one of them a list."""
    hellos: list[str] = []

    def handler(connection: ServerConnection) -> None:
        hellos.append(str(connection.recv(timeout=5)))
        connection.send(json.dumps({"kind": "post", "id": 1, "who": "Ann", "text": "quake here"}))
        connection.send(json.dumps({"kind": "post", "id": 2, "who": "Bo", "text": "lunch"}))
        connection.send(json.dumps([{"kind": "post", "id": 3, "who": "Cy", "text": "big quake"}]))
        time.sleep(2)

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"ws://127.0.0.1:{server.socket.getsockname()[1]}", hellos
        server.shutdown()


def wait_for(live: LiveStream, count: int) -> list[Any]:
    items: list[Any] = []
    ends = time.time() + 5
    while len(items) < count and time.time() < ends:
        items += live(0)
        time.sleep(0.05)
    return items


def test_a_websocket_is_read_in_its_own_thread(socket_server: tuple[str, list[str]]):
    url, hellos = socket_server
    spec = {"name": "posts", "kind": "websocket", "url": url, "hello": {"want": "posts"},
            "id": "id", "sender": "who", "fields": ["text"], "keep": {"text": "quake"}}  # fmt: skip
    live = LiveStream(Stream.model_validate(spec))
    try:
        items = wait_for(live, 2)
    finally:
        live.close()
    assert hellos == ['{"want": "posts"}']
    assert [(i.source, i.payload["body"]) for i in items] == [
        ("ann", "text: quake here"),
        ("cy", "text: big quake"),
    ]
    assert (live.received, live.kept) == (3, 2)


class Events(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for n in range(3):
            self.wfile.write(f': comment\nevent: message\ndata: {{"n": {n},\n'.encode())
            self.wfile.write(f'data: "title": "Page {n}"}}\n\n'.encode())  # data on two lines
            self.wfile.flush()
        time.sleep(4)  # still open while it is read

    def log_message(self, format: str, *args: Any) -> None:
        pass


def test_an_event_stream_joins_each_events_data_lines():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Events)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/stream"
    spec = {"name": "edits", "kind": "events", "url": url, "title": "title", "most": 5}
    try:
        result = peek(Stream.model_validate(spec), seconds=1.5)
    finally:
        server.shutdown()
    assert [i["subject"] for i in result["items"]] == ["Page 0", "Page 1", "Page 2"]
    assert result["received"] == 3 and result["error"] == ""
