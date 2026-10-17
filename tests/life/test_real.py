"""The real-accounts team, against stand-in MCP servers that speak like workspace-mcp (Gmail and
Calendar, read-only) and the Todoist server, so nothing here touches a real account.

What is checked: the feed turns mail and calendar text into items; a model reads claims out of them
and creates the entities; a changed due date reaches the plan and the action resting on it; Todoist
writes are recorded only in shadow mode, wait for a person in manual mode, and run once approved;
the server's own account argument is hidden from the model.
"""

import json
import re
from typing import Any

import pytest

pytest.importorskip("mcp")

import mcp_types as types  # noqa: E402
from mcp.server import Server  # noqa: E402

from graph_agent.frame.mcp import MCPTools  # noqa: E402
from graph_agent.frame.nodes import approvals  # noqa: E402
from graph_agent.harness.llm import ModelReply, ScriptedModel  # noqa: E402
from graph_agent.packs.life import standin  # noqa: E402
from graph_agent.packs.life.real import (  # noqa: E402
    REAL_EXTRACT_PROMPT,
    NeedsSignIn,
    WorkspaceFeed,
    address,
    build_real,
    real_team,
    settings,
)
from graph_agent.stores.memory import MemoryStore  # noqa: E402

ME = "me@gmail.example"


def fake_server(tools: dict[str, tuple[Any, bool, list[str]]]) -> Server[Any]:
    """tools: name -> (handler(arguments) -> text, read_only, parameter names)."""

    async def list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=name,
                    description=name,
                    input_schema={
                        "type": "object",
                        "properties": {p: {"type": "string"} for p in names},
                        "required": names[:1],
                    },
                    annotations=types.ToolAnnotations(read_only_hint=read_only),
                )
                for name, (_, read_only, names) in tools.items()
            ]
        )

    async def call_tool(ctx: Any, params: Any) -> Any:
        handler = tools[params.name][0]
        text = handler(dict(params.arguments or {}))
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    return Server("fake", on_list_tools=list_tools, on_call_tool=call_tool)


class Mailbox:
    """What the stand-in Gmail and Calendar hold, and what was asked of them."""

    def __init__(self) -> None:
        self.mails: dict[str, str] = {}
        self.calendar = "No events found in calendar 'primary'."
        self.emails_seen: list[str] = []

    def search(self, a: dict[str, Any]) -> str:
        self.emails_seen.append(a.get("user_google_email", ""))
        rows = [f"  {i}. Message ID: {m}" for i, m in enumerate(self.mails, 1)]
        return f"Found {len(rows)} messages matching '{a['query']}':\n\n📧 MESSAGES:\n" + "\n".join(
            rows
        )

    def content(self, a: dict[str, Any]) -> str:
        return self.mails[a["message_id"]]

    def events(self, a: dict[str, Any]) -> str:
        return self.calendar


def message(sender: str, to: str, subject: str, body: str) -> str:
    date = "Mon, 19 Oct 2026 09:00:00 +0000"
    return f"Subject: {subject}\nFrom: {sender}\nDate: {date}\nTo: {to}\n\n{body}"


class Todoist:
    def __init__(self) -> None:
        self.tasks: list[dict[str, Any]] = []

    def add(self, a: dict[str, Any]) -> str:
        self.tasks += json.loads(a["tasks"]) if isinstance(a["tasks"], str) else a["tasks"]
        return f"added {len(self.tasks)}"

    def update(self, a: dict[str, Any]) -> str:
        return "updated"


def servers(box: Mailbox, todo: Todoist) -> tuple[Server[Any], Server[Any]]:
    google = fake_server(
        {
            "search_gmail_messages": (box.search, True, ["query", "user_google_email"]),
            "get_gmail_message_content": (box.content, True, ["message_id", "user_google_email"]),
            "get_events": (box.events, True, ["user_google_email"]),
            "list_calendars": (lambda a: "Calendars: primary", True, ["user_google_email"]),
            "send_gmail_message": (lambda a: "sent", False, ["to"]),  # filtered out: not offered
        }
    )
    tasks = fake_server(
        {
            "add-tasks": (todo.add, False, ["tasks"]),
            "update-tasks": (todo.update, False, ["tasks"]),
            "find-tasks": (lambda a: json.dumps(todo.tasks), True, ["searchText"]),
        }
    )
    return google, tasks


def model(box: Mailbox) -> ScriptedModel:
    """Reads claims out of the two mails, then plays the people and actions nodes."""
    local = standin.life_team()

    def policy(system: str, messages: Any, tools: Any) -> ModelReply:
        first = messages[0]["content"]
        if system == REAL_EXTRACT_PROMPT:
            if "send the deck" in first:
                reply = {
                    "new_entities": [["promise-deck", "Promise", "Q4 deck for Ravi"]],
                    "about": ["promise-deck"],
                    "claims": [
                        ["promise-deck", "promise.due", "2026-10-22T17:00"],
                        ["promise-deck", "promise.status", "open"],
                    ],
                }
            elif "no rush" in first.lower():
                reply = {
                    "about": ["promise-deck"],
                    "claims": [["promise-deck", "promise.due", "2026-10-26T17:00"]],
                }
            else:
                reply = {}
            return ModelReply(text=json.dumps(reply), tokens_in=50, tokens_out=20)
        who = re.search(r"You are (\w+):", first)
        if who and who.group(1) == "actions":
            return actions_turn(first, messages)
        return local.complete(system, messages, tools)

    return ScriptedModel(policy, model="real-stand-in")


def actions_turn(first: str, messages: Any) -> ModelReply:
    done = sum(m["role"] == "tool" for m in messages)
    seen = standin.beliefs(first)
    acted = {b for a in standin.actions(first) for b in a.basis}
    todo = [
        b
        for b in seen
        if b.predicate == "plan.task_due" and b.status == "active" and b.told and b.id not in acted
    ]
    if done < len(todo):
        plan = todo[done]
        call = standin.call(
            "add-tasks",
            tasks=[{"content": f"{plan.subject}", "dueString": plan.value}],
            depends_on=[plan.id],
        )
        return ModelReply(tool_calls=[call], tokens_in=40, tokens_out=10)
    return ModelReply(text="done", tokens_in=40, tokens_out=3)


def run(approvals_mode: str, box: Mailbox, todo: Todoist, polls: int = 5):
    google_server, todoist_server = servers(box, todo)
    team = real_team()
    team.settings.approvals = approvals_mode  # type: ignore[assignment]
    runtime, pack, feed = build_real(
        team,
        model(box),
        MemoryStore(),
        google=MCPTools(
            google_server, bind={"user_google_email": ME}, include=["search_*", "get_*", "list_*"]
        ),
        todoist=MCPTools(todoist_server),
        email=ME,
    )
    try:
        runtime.start()
        for i in range(polls):
            if i == 2:  # a day later
                box.mails["m2"] = message(
                    "ravi@partner.example", ME, "Re: Q4 deck", "No rush, Monday is fine. Ravi"
                )
            runtime.step()
    finally:
        runtime.close()
    return runtime, pack, feed


def first_mail(box: Mailbox) -> None:
    box.mails["m1"] = message(
        ME, "ravi@partner.example", "Q4 deck", "Sure, I will send the deck by Thursday 17:00."
    )


def test_the_feed_reads_mail_and_calendar_as_items_with_the_senders_as_sources():
    box = Mailbox()
    first_mail(box)
    box.mails["m0"] = message("Ravi <Ravi@Partner.example>", ME, "Hello", "hi")
    box.calendar = "Successfully retrieved 1 events: - Standup (2026-10-20T09:00)"
    google, _ = servers(box, Todoist())
    feed = WorkspaceFeed(MCPTools(google, bind={"user_google_email": ME}), ME)
    items = feed.mail(0)
    by_id = {i.id: i for i in items}
    assert by_id["m1"].kind == "sent" and by_id["m1"].source == "me"
    assert by_id["m0"].source == "ravi@partner.example"
    assert (
        by_id["m1"].payload["subject"] == "Q4 deck"
        and "send the deck" in by_id["m1"].payload["body"]
    )
    assert feed.mail(1) == []  # already seen
    (event,) = feed.calendar(0)
    assert event.source == "calendar" and feed.calendar(1) == []  # unchanged: nothing new
    assert address("Ravi <Ravi@Partner.example>") == "ravi@partner.example"
    assert box.emails_seen == [ME, ME]  # the account is filled in on every call


def test_the_server_is_asked_for_what_it_may_do_and_the_account_is_hidden_from_the_model():
    box = Mailbox()
    google, todo = servers(box, Todoist())
    tools = MCPTools(
        google, bind={"user_google_email": ME}, include=["search_*", "get_*", "list_*"]
    )
    names = {t.name: t for t in tools.list_tools()}
    assert "send_gmail_message" not in names  # never offered, whatever the server has
    assert "user_google_email" not in names["search_gmail_messages"].input_schema["properties"]
    assert names["search_gmail_messages"].input_schema["required"] == ["query"]
    assert all(not t.outward for t in names.values())
    writes = {t.name: t for t in MCPTools(todo).list_tools()}
    assert writes["add-tasks"].outward and not writes["find-tasks"].outward
    tools.close()


def test_a_promise_in_sent_mail_becomes_a_task_and_a_changed_date_reaches_it():
    box, todo = Mailbox(), Todoist()
    first_mail(box)
    runtime, pack, _ = run("auto", box, todo)
    assert set(runtime.entities) >= {"promise-deck"}
    assert pack.extracted["m1"] == [
        ("promise-deck", "promise.due", "2026-10-22T17:00"),
        ("promise-deck", "promise.status", "open"),
    ]
    due = [
        b for b in runtime.store.beliefs("people", subject="promise-deck", predicate="promise.due")
    ]
    assert [(b.value, b.status) for b in due] == [
        ("2026-10-22T17:00", "retracted"),
        ("2026-10-26T17:00", "active"),
    ]
    held = [e for e in runtime.log.events if e.kind == "held"]
    assert held and held[0].data["tool"] == "add-tasks" and held[0].data["was_done"]
    assert [t["dueString"] for t in todo.tasks] == ["2026-10-22T17:00", "2026-10-26T17:00"]


def test_shadow_mode_records_what_the_team_would_do_and_runs_nothing():
    box, todo = Mailbox(), Todoist()
    first_mail(box)
    runtime, _, _ = run("shadow", box, todo)
    book = list(approvals(runtime).proposals.values())
    assert book and todo.tasks == []
    assert {p.status for p in book} <= {"shadow", "held", "reviewed"}
    assert any(p.status in ("held", "reviewed") for p in book)  # the changed date held the first
    shadowed = [e for e in runtime.log.events if e.kind == "action"]
    assert shadowed and all(e.data["status"] == "shadow" for e in shadowed)


def test_manual_mode_waits_for_a_person_and_nothing_runs_meanwhile():
    box, todo = Mailbox(), Todoist()
    first_mail(box)
    runtime, _, _ = run("manual", box, todo, polls=2)
    (proposal,) = approvals(runtime).proposals.values()
    assert proposal.tool == "add-tasks" and proposal.status == "pending"
    assert todo.tasks == []


def test_a_missing_setting_is_named_not_leaked(monkeypatch):
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_CLIENT_API", "USER_GOOGLE_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("graph_agent.packs.life.real.load_env", lambda: None)
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("TODOIST_API_KEY", "token-value")
    with pytest.raises(ValueError) as error:
        settings()
    assert "GOOGLE_OAUTH_CLIENT_ID" in str(error.value) and "USER_GOOGLE_EMAIL" in str(error.value)
    assert "secret" not in str(error.value).lower().replace("client_secret", "")
    assert "super-secret-value" not in str(error.value)


def test_a_sign_in_prompt_from_the_server_is_surfaced_not_swallowed():
    box = Mailbox()
    box.search = lambda a: (  # type: ignore[method-assign]
        "ACTION REQUIRED: Google Authentication Needed. Authorize: https://accounts.example/auth?x=1"
    )
    google, _ = servers(box, Todoist())
    google = fake_server(
        {"search_gmail_messages": (box.search, True, ["query", "user_google_email"])}
    )
    feed = WorkspaceFeed(MCPTools(google, bind={"user_google_email": ME}), ME)
    with pytest.raises(NeedsSignIn, match="accounts.example"):
        feed.mail(0)
