"""Streams: live data on the open internet (a websocket, an event stream, a page polled), read
without any account, that come to a team as items, like a feed (feeds.py) but with no MCP server.

A stream says where it is and how to read what it sends:

    {"name": "github-status", "kind": "poll", "every": 120,
     "url": "https://www.githubstatus.com/api/v2/incidents.json",
     "items": "incidents", "id": "id", "title": "name",
     "fields": ["name", "status", "impact", "updated_at"],
     "trusted": true}

  kind      "websocket" (wss://, `hello` is sent once connected: a subscription), "events" (a
            server-sent event stream), or "poll" (a page read every `every` seconds, "json" or
            "rss" by `format`)
  items     where a page (or a message) lists its items, as a path ("incidents"); none: the
            message is one item (a list: each of its elements); an RSS page's items are found
  id        what names an item. The same id with other `fields` comes again, as an update: a
            reading revised, an incident resolved. None: every message is new
  sender    who an item is from ("user", "did"): a source in the graph that can be caught lying
            and distrusted. None: the stream itself, which `trusted` makes a system of record
  fields    what the team reads of each item ("path" or "path|ms", "path|s": an epoch time, as
            ISO 8601); none: all of it
  keep      path -> regex: only the items matching every one of these; `drop`: never those
            matching any
  most      at most this many items a poll, the newest (a firehose is cut down, not queued)

A path is keys and list indexes with dots ("commit.record.text", "lineStatuses.0.reason"); in
an RSS or Atom item, the tags' own names ("title", "alertlevel"). The streams that need no key
are listed in packs/apps/public_streams.py.

A websocket or event stream is read in a thread of its own from the start of the run, and what
came since the last tick is handed over each tick; a page is read when `every` seconds have gone.
A stream never follows a redirect, and reads at most MAX_BYTES of a page.
"""

import hashlib
import json
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal, cast

import httpx
from pydantic import Field, model_validator

from .connections import Strict, resolve
from .runtime import Item, Runtime

USER_AGENT = "groundwork/0.1 (a team of agents reading public data)"
MAX_BYTES = 6_000_000  # a page larger than this is not read
BUFFER = 500  # what a websocket keeps between two ticks, at most (the newest)


class Stream(Strict):
    """Live data a team reads (see the module's docstring for each field)."""

    name: str  # the stream's name in the team ("quakes"); its node is "<name>-feed"
    label: str = ""
    about: str = ""  # one line for the console: what it is, how much it sends
    url: str  # "$NAME" in it, or in headers: one of your keys
    kind: Literal["websocket", "events", "poll"] = "poll"
    format: Literal["json", "rss"] = "json"
    hello: Any = None
    headers: dict[str, str] = Field(default_factory=dict[str, str])
    items: str | None = None
    id: str | None = None
    sender: str | None = None
    title: str | None = None
    fields: list[str] = Field(default_factory=list[str])
    keep: dict[str, str] = Field(default_factory=dict[str, str])
    drop: dict[str, str] = Field(default_factory=dict[str, str])
    every: int = Field(default=60, ge=10)  # poll: seconds between two reads
    newest_first: bool = True  # a page lists its newest items first
    most: int = Field(default=5, ge=1, le=50)
    trusted: bool = False
    limit: int = 3000  # characters of each item kept

    @model_validator(mode="after")
    def _check(self) -> "Stream":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.name):
            raise ValueError(f"stream name {self.name!r}: use lowercase letters, digits, -")
        scheme = self.url.split(":", 1)[0].lower()
        wanted = ("wss", "ws") if self.kind == "websocket" else ("https", "http")
        if scheme not in wanted:
            raise ValueError(f"stream {self.name}: a {self.kind} url starts with {wanted[0]}://")
        for pattern in [*self.keep.values(), *self.drop.values()]:
            try:
                re.compile(pattern)
            except re.error as error:
                raise ValueError(
                    f"stream {self.name}: {pattern!r} is not a regex: {error}"
                ) from None
        return self


def stream_of(entry: Mapping[str, Any], presets: Mapping[str, dict[str, Any]]) -> Stream:
    """One entry of a team's streams: a preset of the catalogue (with changes), or a stream in
    full. A preset's filters can be added to: {"preset": "bluesky-posts", "keep": {...}}."""
    entry = dict(entry)
    preset = entry.pop("preset", None)
    if preset is None:
        return Stream.model_validate(entry)
    if preset not in presets:
        raise ValueError(f"no stream {preset!r}; the streams are {', '.join(sorted(presets))}")
    base = presets[preset]
    merged = {"name": preset, **base, **entry}
    for key in ("keep", "drop"):  # yours narrow the preset's, they do not replace them
        merged[key] = {**base.get(key, {}), **entry.get(key, {})}
    return Stream.model_validate(merged)


# ---- reading one item ---------------------------------------------------------------------------


def at(data: Any, path: str | None) -> Any:
    """The value at a dotted path ("a.b.0.c"); None where there is none. No path: `data`."""
    if not path:
        return data
    for key in path.split("."):
        if isinstance(data, dict):
            data = cast(dict[str, Any], data).get(key)
        elif isinstance(data, list) and key.isdigit():
            found = cast(list[Any], data)
            data = found[int(key)] if int(key) < len(found) else None
        else:
            return None
    return data


def shown(data: Any, field: str) -> tuple[str, str]:
    """(name, value as text) of one of `fields`: "path", or "path|ms" / "path|s" (epoch times)."""
    path, _, unit = field.partition("|")
    value = at(data, path)
    if unit in ("ms", "s") and isinstance(value, (int, float)):
        seconds = value / 1000 if unit == "ms" else value
        value = datetime.fromtimestamp(seconds, UTC).isoformat(timespec="seconds")
    if value is None:
        return path, ""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    return path, text


def matches(data: Any, rules: Mapping[str, str]) -> list[bool]:
    return [re.search(pattern, shown(data, path)[1]) is not None for path, pattern in rules.items()]


def wanted(stream: Stream, data: Any) -> bool:
    return all(matches(data, stream.keep)) and not any(matches(data, stream.drop))


def rss_items(text: str) -> list[dict[str, Any]]:
    """An RSS or Atom page's items, each as {tag: text}, the tags' own names without their
    namespace (an Atom link: its href)."""
    root = ET.fromstring(text.lstrip("﻿"))
    found: list[dict[str, Any]] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in ("item", "entry"):
            continue
        item: dict[str, Any] = {}
        for child in node.iter():
            if child is node:
                continue
            tag = child.tag.rsplit("}", 1)[-1]
            value = (child.text or "").strip() or child.get("href", "") or child.get("value", "")
            if value and tag not in item:
                item[tag] = value
        found.append(item)
    return found


def listed(stream: Stream, data: Any) -> list[Any]:
    """The items in one page or message."""
    found = at(data, stream.items)
    if isinstance(found, list):
        return cast(list[Any], found)
    return [] if found is None else [found]


# ---- a stream, read --------------------------------------------------------------------------


class LiveStream:
    """One stream of a run: call it with the tick, get the items that came since the last.
    `get`: how a page is read (url, headers) -> its text (tests give their own)."""

    def __init__(
        self,
        stream: Stream,
        secrets: Mapping[str, str] | None = None,
        get: Callable[[str, dict[str, str]], str] | None = None,
    ):
        self.stream = stream
        self.url = resolve(stream.url, secrets)
        self.headers = {
            "User-Agent": USER_AGENT,
            **{k: resolve(v, secrets) for k, v in stream.headers.items()},
        }
        self.get = get or read_page
        self.seen: dict[str, str] = {}  # an item's id -> the digest of what the team read of it
        self.waiting: deque[Any] = deque(maxlen=BUFFER)  # a websocket's items, until the tick
        self.lock = threading.Lock()
        self.read_at = 0.0  # when the page was last read
        self.received = 0  # items that came at all ...
        self.kept = 0  # ... of which matched keep and drop ...
        self.skipped = 0  # ... of which were more than `most` at once
        self.error = ""  # what last went wrong, for the console
        self.closed = threading.Event()
        self._thread: threading.Thread | None = None
        self._response: httpx.Response | None = None

    # ---- what the team gets --------------------------------------------------------------------

    def __call__(self, tick: int) -> list[Item]:
        stream = self.stream
        if stream.kind == "poll":
            if time.time() - self.read_at < stream.every:
                return []
            self.read_at = time.time()
            try:
                page = self.get(self.url, self.headers)
                data = rss_items(page) if stream.format == "rss" else json.loads(page)
            except (httpx.HTTPError, ValueError, ET.ParseError) as error:
                self.error = f"{type(error).__name__}: {str(error)[:200]}"
                return []
            self.error = ""
            found = listed(stream, data) if stream.format == "json" else data
            if stream.newest_first:
                found = list(reversed(found))  # oldest first, so an update comes after the first
            new = [d for d in found if self._counted(d) and self._new(d)]
        else:
            self._start()
            with self.lock:
                new, self.waiting = list(self.waiting), deque(maxlen=BUFFER)
        self.skipped += max(0, len(new) - stream.most)
        return [self._item(d, tick) for d in new[-stream.most :]]

    def _counted(self, data: Any) -> bool:
        self.received += 1
        if not wanted(self.stream, data):
            return False
        self.kept += 1
        return True

    def _new(self, data: Any) -> bool:
        """Whether the team has not read this item yet, or not as it is now (an update)."""
        if self.stream.id is None:
            return True
        key = shown(data, self.stream.id)[1]
        digest = self._digest(data)
        if self.seen.get(key) == digest:
            return False
        self.seen[key] = digest
        return True

    def _digest(self, data: Any) -> str:
        text = self._text(data)
        return hashlib.sha256(text.encode()).hexdigest()[:8]

    def _text(self, data: Any) -> str:
        if not self.stream.fields:
            return json.dumps(data, ensure_ascii=False, sort_keys=True)
        lines = [shown(data, f) for f in self.stream.fields]
        return "\n".join(f"{name}: {value}" for name, value in lines if value)

    def _item(self, data: Any, tick: int) -> Item:
        stream = self.stream
        text = self._text(data)
        digest = hashlib.sha256(text.encode()).hexdigest()[:8]
        key = shown(data, stream.id)[1] if stream.id else ""
        sender = shown(data, stream.sender)[1] if stream.sender else ""
        source = sender.lower() or stream.name
        title = shown(data, stream.title)[1] if stream.title else ""
        return Item(
            id=f"{stream.name}-{key or digest}-{digest}"[:120],
            kind=stream.name,
            tick=tick,
            source=source,
            payload={
                "from": source,
                "to": "",
                "subject": title[:200] or stream.label or stream.name,
                "body": text[: stream.limit],
            },
        )

    # ---- a websocket or event stream, read in its own thread -----------------------------------

    def _start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._keep_reading, daemon=True)
            self._thread.start()

    def _keep_reading(self) -> None:
        wait = 2.0
        while not self.closed.is_set():
            started = time.time()
            try:
                if self.stream.kind == "websocket":
                    self._read_socket()
                else:
                    self._read_events()
                self.error = "" if self.closed.is_set() else "the stream ended; reconnecting"
            except Exception as error:  # noqa: BLE001  the run goes on; the console shows why
                if self.closed.is_set():
                    return
                self.error = f"{type(error).__name__}: {str(error)[:200]}"
            if time.time() - started > 60:
                wait = 2.0  # it was working: try again soon
            self.closed.wait(wait)
            wait = min(wait * 2, 120.0)

    def _arrived(self, message: str) -> None:
        try:
            data = json.loads(message)
        except ValueError:
            return
        for found in listed(self.stream, data):
            if self._counted(found) and self._new(found):
                with self.lock:
                    self.waiting.append(found)

    def _read_socket(self) -> None:
        from websockets.sync.client import connect

        with connect(
            self.url,
            additional_headers=self.headers,
            open_timeout=15,
            max_size=2**22,
            user_agent_header=USER_AGENT,
        ) as socket:
            if self.stream.hello is not None:
                socket.send(json.dumps(self.stream.hello))
            self.error = ""
            while not self.closed.is_set():
                try:
                    message = socket.recv(timeout=1)
                except TimeoutError:
                    continue
                self._arrived(message if isinstance(message, str) else message.decode())

    def _read_events(self) -> None:
        headers = {**self.headers, "Accept": "text/event-stream"}
        timeout = httpx.Timeout(15, read=90)
        with httpx.stream("GET", self.url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            self._response = response
            self.error = ""
            data: list[str] = []
            for line in response.iter_lines():
                if self.closed.is_set():
                    return
                if line.startswith("data:"):
                    data.append(line[5:].strip())
                elif not line and data:
                    self._arrived("\n".join(data))
                    data = []

    def close(self) -> None:
        self.closed.set()
        if self._response is not None:
            try:
                self._response.close()  # an event stream waiting for its next line stops
            except Exception:  # noqa: BLE001
                pass


def read_page(url: str, headers: dict[str, str]) -> str:
    """A page's text: never following a redirect, never more than MAX_BYTES."""
    with httpx.stream("GET", url, headers=headers, timeout=20) as response:
        response.raise_for_status()
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_BYTES:
                raise ValueError(f"the page is larger than {MAX_BYTES // 1_000_000} MB")
            chunks.append(chunk)
    return b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")


def peek(
    stream: Stream,
    secrets: Mapping[str, str] | None = None,
    seconds: float = 8.0,
    get: Callable[[str, dict[str, str]], str] | None = None,
) -> dict[str, Any]:
    """Read a stream for a few seconds (a page: once) and say what the team would get: how many
    items came, how many matched, and the first few as the team reads them."""
    live = LiveStream(stream, secrets, get)
    try:
        items = live(0)
        if stream.kind != "poll":
            ends = time.time() + seconds
            while time.time() < ends and len(items) < stream.most:
                time.sleep(0.25)
                items += live(0)
    finally:
        live.close()
    return {
        "received": live.received,
        "kept": live.kept,
        "error": live.error,
        "items": [
            {"from": i.source, "subject": i.payload["subject"], "body": i.payload["body"][:600]}
            for i in items[: stream.most]
        ],
    }


def attach_streams(
    rt: Runtime,
    streams: list[Stream],
    secrets: Mapping[str, str] | None = None,
    get: Callable[[str, dict[str, str]], str] | None = None,
) -> dict[str, LiveStream]:
    """Give the run its streams (a stream node with config feed "quakes" reads the one named
    "quakes"); they stop when the run closes. `get`: how pages are read (tests)."""
    opened: dict[str, LiveStream] = {}
    for stream in streams:
        if stream.name in rt.feeds:
            raise ValueError(f"two feeds are named {stream.name!r}: rename one")
        live = LiveStream(stream, secrets, get)
        rt.feeds[stream.name] = live
        rt.closers.append(live.close)
        opened[stream.name] = live
    return opened
