"""Feeds: a connection's tools, polled every tick, bring the news to the team as items.

A feed (connections.Feed) polls one tool. Two shapes cover most servers:

  a list    `ids` is a regex finding each item's id in the result (a mailbox search); each new
            one is read with the `open` tool and becomes an item, oldest first, once only
  a page    no `ids`: the whole result is one item, whenever it differs from the last poll (a
            calendar's next 30 days)

Who an item comes from matters: an outside sender is a node in the graph, so it can be caught
lying and distrusted. With `sender`, that header ("From: Ann <ann@x.example>") names the source,
and the person's own address becomes "me"; without, the source is the feed itself, which a
`trusted` feed makes a system of record (its items are evidence).

The items carry no claims: the pack's extractor reads them (see packs/apps).
"""

import hashlib
import re
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from .connections import Connection, Feed, connect, resolve
from .mcp import MCPTools
from .runtime import Item, Runtime


class NeedsSignIn(RuntimeError):
    """The server wants the person to sign in first; the message holds what it said (a link)."""


ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
TODAY = re.compile(r"\{today([+-]\d+)?\}")


def address(text: str) -> str:
    """The email address in a header value such as 'Ann <ann@x.example>'."""
    found = ADDRESS.search(text)
    return found.group(0).lower() if found else text.strip().lower()


def header(text: str, name: str) -> str:
    """The value of a 'Name: value' line in `text` ("" if there is none)."""
    found = re.search(rf"^\s*{re.escape(name)}:\s*(.+)$", text, re.MULTILINE | re.IGNORECASE)
    return found.group(1).strip() if found else ""


def dated(value: Any, today: date) -> Any:
    """An argument with "{today}", "{today+30}" or "{today-1}" filled in (as 2026-10-17)."""
    if not isinstance(value, str):
        return value

    def day(match: re.Match[str]) -> str:
        return (today + timedelta(days=int(match.group(1) or 0))).isoformat()

    return TODAY.sub(day, value)


class ConnectionFeed:
    """One feed of one connection: call it with the tick, get the new items."""

    def __init__(
        self, tools: MCPTools, feed: Feed, today: date | None = None, me: str | None = None
    ):
        self.tools = tools
        self.feed = feed
        self.me = (resolve(feed.me) if me is None else me).lower()  # me: feed.me, resolved
        self.today = today  # None: the real date at each poll
        self.seen: set[str] = set()
        self.last = ""  # a page feed: the digest of the last result

    def __call__(self, tick: int) -> list[Item]:
        feed = self.feed
        if tick % feed.every:
            return []
        today = self.today or date.today()
        args = {k: dated(v, today) for k, v in feed.args.items()}
        text = self._checked(self.tools.call(feed.tool, args))
        if feed.ids is None:
            return self._page(text, tick)
        found = list(dict.fromkeys(re.findall(feed.ids, text)))
        new = [i for i in found if i not in self.seen]
        if feed.newest_first:
            new.reverse()
        items: list[Item] = []
        for item_id in new:
            self.seen.add(item_id)
            if feed.open is None:  # no reader: the line that names it is all there is
                body = next((line for line in text.splitlines() if item_id in line), item_id)
            else:
                body = self._checked(self.tools.call(feed.open, {feed.open_arg: item_id}))
            items.append(self._item(f"{feed.name}-{item_id}", body, tick))
        return items

    def _page(self, text: str, tick: int) -> list[Item]:
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        if digest == self.last:
            return []
        self.last = digest
        return [self._item(f"{self.feed.name}-{digest}", text, tick)]

    def _item(self, item_id: str, text: str, tick: int) -> Item:
        feed = self.feed
        source, kind, to = feed.name, feed.name, ""
        if feed.sender is not None:
            source = address(header(text, feed.sender)) or "unknown"
            to = address(header(text, "To"))
            if self.me and source == self.me:
                source, kind = "me", "sent"
        return Item(
            id=item_id,
            kind=kind,
            tick=tick,
            source=source,
            payload={
                "from": source,
                "to": to,
                "subject": header(text, "Subject") or feed.name,
                "body": text[: feed.limit],
            },
        )

    def _checked(self, text: str) -> str:
        """Raise NeedsSignIn when the server answered with a sign-in request instead."""
        word = self.feed.sign_in
        lowered = text.lower()
        listed = self.feed.ids is not None and re.search(self.feed.ids, text)
        if word and word.lower() in lowered and "http" in lowered and not listed:
            raise NeedsSignIn(text.strip()[:1200])
        return text


def attach(
    rt: Runtime,
    connections: list[Connection],
    servers: Mapping[str, Any] | None = None,
    today: date | None = None,
) -> dict[str, MCPTools]:
    """Connect each connection and give the run its tools and feeds (a stream node with
    config feed "mail" reads the feed named "mail"). The connections close with the run.
    `servers`: connection name -> a server to use instead (tests)."""
    servers = servers or {}
    opened: dict[str, MCPTools] = {}
    try:
        for connection in connections:
            tools = connect(connection, servers.get(connection.name))
            opened[connection.name] = tools
            rt.providers.append(tools)
            rt.closers.append(tools.close)
            for feed in connection.feeds:
                if feed.name in rt.feeds:
                    raise ValueError(f"two feeds are named {feed.name!r}: rename one")
                me = connection.resolve(feed.me)
                rt.feeds[feed.name] = ConnectionFeed(tools, feed, today, me)
    except BaseException:
        rt.close()  # what did open is not left running
        raise
    return opened
