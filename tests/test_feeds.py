"""Feeds: a connection's tools polled for news, which reach the team as items."""

from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp")

import mcp_types as types  # noqa: E402
from mcp.server import Server  # noqa: E402

from graph_agent.frame.connections import Connection, Feed, connect  # noqa: E402
from graph_agent.frame.feeds import ConnectionFeed, NeedsSignIn, attach, dated  # noqa: E402
from graph_agent.frame.runtime import Runtime  # noqa: E402
from graph_agent.frame.spec import TeamSpec  # noqa: E402
from graph_agent.stores.memory import MemoryStore  # noqa: E402


class Inbox:
    """A mailbox server that speaks like most do: a search lists ids, a read gives headers."""

    def __init__(self) -> None:
        self.mails: dict[str, str] = {}  # id -> full text, oldest first
        self.page = "No events."
        self.asked: list[dict[str, Any]] = []

    def add(self, mail_id: str, sender: str, subject: str, body: str) -> None:
        self.mails[mail_id] = f"From: {sender}\nTo: Me <me@x.example>\nSubject: {subject}\n\n{body}"

    def handle(self, name: str, a: dict[str, Any]) -> str:
        self.asked.append({"tool": name, **a})
        if name == "search":
            newest_first = reversed(list(self.mails))
            return "Found:\n" + "\n".join(f"- Message ID: {i}" for i in newest_first)
        if name == "read":
            return self.mails[a["message_id"]]
        return self.page

    def server(self) -> Server[Any]:
        async def list_tools(ctx: Any, params: Any) -> Any:
            return types.ListToolsResult(
                tools=[
                    types.Tool(
                        name=n,
                        description=n,
                        input_schema={"type": "object", "properties": {}},
                        annotations=types.ToolAnnotations(read_only_hint=True),
                    )
                    for n in ("search", "read", "events")
                ]
            )

        async def call_tool(ctx: Any, params: Any) -> Any:
            text = self.handle(params.name, dict(params.arguments or {}))
            return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

        return Server("inbox", on_list_tools=list_tools, on_call_tool=call_tool)


MAIL = Feed(
    name="mail",
    tool="search",
    ids=r"Message ID:\s*(\w+)",
    open="read",
    open_arg="message_id",
    sender="From",
    me="me@x.example",
    sign_in="authentication",
)
EVENTS = Feed(
    name="calendar",
    tool="events",
    args={"from": "{today-1}", "to": "{today+30}"},
    trusted=True,
    every=2,
)
APP = Connection(name="box", command="unused", feeds=[MAIL, EVENTS])


def open_feed(inbox: Inbox, feed: Feed) -> ConnectionFeed:
    return ConnectionFeed(connect(APP, inbox.server()), feed, today=date(2026, 10, 17))


def test_new_mail_arrives_once_oldest_first_from_its_sender():
    inbox = Inbox()
    inbox.add("a1", "Ann <ann@x.example>", "Dinner", "Friday at 8?")
    inbox.add("a2", "Me <me@x.example>", "Re: Dinner", "Yes.")
    feed = open_feed(inbox, MAIL)
    try:
        first = feed(0)
        assert [(i.id, i.source, i.kind) for i in first] == [
            ("mail-a1", "ann@x.example", "mail"),
            ("mail-a2", "me", "sent"),  # the person's own mail comes from "me"
        ]
        assert (
            first[0].payload["subject"] == "Dinner" and "Friday at 8?" in first[0].payload["body"]
        )
        assert first[0].payload["to"] == "me@x.example"
        assert feed(1) == []  # nothing new
        inbox.add("a3", "Ann <ann@x.example>", "Dinner moved", "Saturday instead.")
        assert [i.id for i in feed(2)] == ["mail-a3"]
    finally:
        feed.tools.close()


def test_a_page_comes_when_it_changes_on_its_schedule_with_dates_filled_in():
    inbox = Inbox()
    feed = open_feed(inbox, EVENTS)
    try:
        assert [i.source for i in feed(0)] == ["calendar"]
        assert inbox.asked[-1] == {"tool": "events", "from": "2026-10-16", "to": "2026-11-16"}
        assert feed(1) == []  # every 2 ticks: not polled
        assert feed(2) == []  # polled, unchanged
        inbox.page = "Dinner with Ann, Sat 20:00."
        assert [i.payload["body"] for i in feed(4)] == ["Dinner with Ann, Sat 20:00."]
    finally:
        feed.tools.close()


def test_a_sign_in_request_is_not_taken_for_mail():
    inbox = Inbox()
    inbox.mails = {}
    inbox.handle = lambda name, a: "Authentication needed: open https://accounts.example/x"
    feed = open_feed(inbox, MAIL)
    try:
        with pytest.raises(NeedsSignIn, match="https://accounts.example/x"):
            feed(0)
    finally:
        feed.tools.close()


def test_dates():
    today = date(2026, 12, 31)
    assert dated("{today}", today) == "2026-12-31"
    assert dated("after {today+1}", today) == "after 2027-01-01"
    assert dated(50, today) == 50


def test_attach_gives_the_run_the_tools_and_the_feeds_and_closes_them_with_it():
    inbox = Inbox()
    inbox.add("a1", "Ann <ann@x.example>", "Dinner", "Friday at 8?")
    rt = Runtime(TeamSpec(name="t"), pack=None, store=MemoryStore())  # type: ignore[arg-type]
    opened = attach(rt, [APP], servers={"box": inbox.server()}, today=date(2026, 10, 17))
    assert set(rt.feeds) == {"mail", "calendar"}
    assert [t.name for t in rt.providers[0].list_tools()] == [
        "box_search",
        "box_read",
        "box_events",
    ]
    assert [i.id for i in rt.feeds["mail"](0)] == ["mail-a1"]
    rt.close()
    assert opened["box"]._stop is not None and opened["box"]._stop.is_set()


def test_two_feeds_with_one_name_are_refused():
    twin = Connection(name="other", command="unused", feeds=[MAIL])
    rt = Runtime(TeamSpec(name="t"), pack=None, store=MemoryStore())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="two feeds are named 'mail'"):
        attach(rt, [APP, twin], servers={"box": Inbox().server(), "other": Inbox().server()})
    assert rt.closers == []  # the first one was closed again
