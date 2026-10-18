"""Your own agents on your own apps: a short agents file becomes a team that runs on MCP servers.

The servers here are stand-ins that speak like the presets' servers (Gmail through workspace-mcp,
Todoist), so nothing touches a real account. What is checked: the agents file becomes the team it
describes, with its mistakes named in plain words; a promise in sent mail becomes a plan and a
Todoist task resting on it; when the date moves, the task is held; shadow mode runs nothing.
"""

import json
import re
from datetime import date
from typing import Any

import pytest

pytest.importorskip("mcp")

import mcp_types as types  # noqa: E402
from mcp.server import Server  # noqa: E402

from graph_agent.frame.connections import Connection, from_entry  # noqa: E402
from graph_agent.frame.nodes import approvals  # noqa: E402
from graph_agent.frame.runtime import Runtime  # noqa: E402
from graph_agent.harness.llm import ChatMessage, ModelReply, ScriptedModel, ToolCall  # noqa: E402
from graph_agent.packs.apps.pack import EXTRACT_PROMPT, PLAN, vocabulary  # noqa: E402
from graph_agent.packs.apps.run import EXAMPLE_AGENTS, build_apps  # noqa: E402
from graph_agent.packs.apps.setup import Setup, problems, team_of, things_of  # noqa: E402
from graph_agent.stores.memory import MemoryStore  # noqa: E402

ME = "me@gmail.example"


def example() -> Setup:
    return Setup.model_validate(EXAMPLE_AGENTS)


def connections() -> list[Connection]:
    return [from_entry({"preset": "google"}), from_entry({"preset": "todoist"})]


# ---- the agents file -------------------------------------------------------------------------


def test_a_few_lines_per_agent_become_the_whole_team():
    team = team_of(example(), connections())
    kinds = {n.id: n.type for n in team.nodes}
    assert kinds == {
        "mail-feed": "stream",
        "calendar-feed": "stream",
        "router": "router",
        "inbox": "agent",
        "calendar": "agent",
        "people": "agent",
        "tasks": "responder",  # it carries out: woken by plans, reads no mail
        "checker": "checker",
    }
    assert team.node("router").config["fallback"] == "inbox"  # the first agent gets the rest
    assert team.node("tasks").tools == ["todoist_*"]
    assert team.settings.approvals == "shadow"  # nothing runs until you say so
    links = {(link.kind, link.src, link.dst) for link in team.links}
    assert ("owns", "people", "type:Promise") in links
    assert ("talks_to", "people", "tasks") in links and ("talks_to", "tasks", "inbox") in links
    assert ("watches", "tasks", "people") in links
    assert ("feeds", "mail-feed", "router") in links


def test_mistakes_are_named_in_words_you_can_act_on():
    setup = Setup.model_validate(
        {
            "agents": [
                {"name": "Inbox", "job": "x"},
                {"name": "money", "job": "x", "looks_after": ["Invoice"], "talks_to": ["bank"]},
                {"name": "router", "job": "x", "apps": ["slack_*"]},
            ],
            "unowned": "nobody",
        }
    )
    wrong = problems(setup, connections(), tools=["google_get_events", "todoist_add-tasks"])
    assert wrong == [
        "agent 'Inbox': use a short lowercase name (letters, digits, -)",
        "agent money: the team keeps track of no 'Invoice'; add it to the kinds of thing",
        "agent money: talks_to 'bank', who is not an agent",
        "agent 'router': that name is taken; pick another",
        "agent router: no app tool matches 'slack_*'",
        "unowned: 'nobody' is not an agent",
    ]
    with pytest.raises(ValueError, match="talks_to 'bank'"):
        team_of(setup, connections())


def test_your_own_kinds_of_thing_join_the_vocabulary():
    setup = Setup.model_validate(
        {"agents": [{"name": "money", "job": "x"}], "things": {"Invoice": ["due", "amount"]}}
    )
    words = vocabulary(things_of(setup))
    assert words["invoice.due"] == "invoice {subject} due {value}"
    assert "event.starts" not in words  # a team keeps track of its own kinds only
    assert words[PLAN] == "plan for {subject}: {value}"
    personal = vocabulary(things_of(example()))  # the example's are a personal team's
    assert personal["event.starts"] == "event {subject} starts {value}"


# ---- a run on stand-in servers ---------------------------------------------------------------


def fake_server(name: str, tools: dict[str, tuple[Any, bool]]) -> Server[Any]:
    """tools: name -> (handler(arguments) -> text, read_only)."""

    async def list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool,
                    description=tool,
                    input_schema={"type": "object", "properties": {}},
                    annotations=types.ToolAnnotations(read_only_hint=read_only),
                )
                for tool, (_, read_only) in tools.items()
            ]
        )

    async def call_tool(ctx: Any, params: Any) -> Any:
        text = tools[params.name][0](dict(params.arguments or {}))
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])

    return Server(name, on_list_tools=list_tools, on_call_tool=call_tool)


class Accounts:
    """What the stand-in Gmail, Calendar and Todoist hold."""

    def __init__(self) -> None:
        self.mails: dict[str, str] = {}
        self.tasks: list[dict[str, Any]] = []

    def mail(self, mail_id: str, sender: str, to: str, subject: str, body: str) -> None:
        self.mails[mail_id] = f"Subject: {subject}\nFrom: {sender}\nTo: {to}\n\n{body}"

    def servers(self) -> dict[str, Server[Any]]:
        def search(a: dict[str, Any]) -> str:
            return "\n".join(f"Message ID: {m}" for m in reversed(list(self.mails)))

        def add(a: dict[str, Any]) -> str:
            self.tasks += a["tasks"]
            return f"added {len(a['tasks'])}"

        google = {
            "search_gmail_messages": (search, True),
            "get_gmail_message_content": (lambda a: self.mails[a["message_id"]], True),
            "get_events": (lambda a: "No events.", True),
            "list_calendars": (lambda a: "primary", True),
        }
        todoist = {
            "find-tasks": (lambda a: json.dumps(self.tasks), True),
            "add-tasks": (add, False),
            "update-tasks": (lambda a: "updated", False),
        }
        return {"google": fake_server("google", google), "todoist": fake_server("todoist", todoist)}


def model(holder: dict[str, Runtime]) -> ScriptedModel:
    """Reads the mails' claims, then plays people (plans a task per open promise) and tasks
    (adds the task, resting on the plan). Everyone else is done at once."""

    def extract(text: str) -> dict[str, Any]:
        if "send the deck" in text:
            return {
                "new_entities": [["promise-deck", "Promise", "Q4 deck for Ravi"]],
                "about": ["promise-deck"],
                "claims": [
                    ["promise-deck", "promise.due", "2026-10-22T17:00"],
                    ["promise-deck", "promise.status", "open"],
                ],
            }
        if "Monday is fine" in text:
            return {
                "about": ["promise-deck"],
                "claims": [["promise-deck", "promise.due", "2026-10-26T17:00"]],
            }
        return {}

    def policy(system: str, messages: list[ChatMessage], tools: Any) -> ModelReply:
        first = messages[0]["content"]
        if system == EXTRACT_PROMPT:
            return ModelReply(text=json.dumps(extract(first)), tokens_in=50, tokens_out=20)
        rt = holder["rt"]
        me = re.search(r"You are ([\w-]+):", first)
        who = me.group(1) if me else ""
        store = rt.store
        if who == "people":
            plans = [b for b in store.beliefs("people", predicate=PLAN) if b.status == "active"]
            unsent = [p for p in plans if not rt.copies.get(("people", p.id))]
            if unsent:
                return ModelReply(
                    tool_calls=[ToolCall("send", {"to": "tasks", "belief_id": unsent[0].id}, "s")]
                )
            for due in store.beliefs("people", predicate="promise.due"):
                if due.status == "active" and not plans:
                    args = {
                        "subject": due.subject,
                        "predicate": PLAN,
                        "value": f"add a task due {due.value}",
                        "depends_on": [due.id],
                    }
                    return ModelReply(tool_calls=[ToolCall("assert_belief", args, "a")])
        if who == "tasks":
            acted = {b for p in approvals(rt).proposals.values() for b in p.basis}
            for plan in store.beliefs("tasks", predicate=PLAN):
                if plan.status == "active" and plan.id not in acted:
                    due = str(plan.value).removeprefix("add a task due ")
                    args = {
                        "tasks": [{"content": "Q4 deck for Ravi", "dueString": due}],
                        "depends_on": [plan.id],
                    }
                    return ModelReply(tool_calls=[ToolCall("todoist_add-tasks", args, "t")])
        return ModelReply(text="done")

    return ScriptedModel(policy, model="apps-test")


def run(mode: str, accounts: Accounts, polls: int = 5) -> Runtime:
    setup = example()
    setup.approvals = mode  # type: ignore[assignment]
    holder: dict[str, Runtime] = {}
    rt, _ = build_apps(
        team_of(setup, connections()),
        connections(),
        model(holder),
        MemoryStore(),
        servers=accounts.servers(),
        today=date(2026, 10, 19),
    )
    holder["rt"] = rt
    try:
        rt.start()
        for poll in range(polls):
            if poll == 2:  # a day later, Ravi writes back
                accounts.mail(
                    "m2",
                    "Ravi <ravi@partner.example>",
                    ME,
                    "Re: Q4 deck",
                    "No rush, Monday is fine. Ravi",
                )
            rt.step()
    finally:
        rt.close()
    return rt


@pytest.fixture(autouse=True)
def account(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("USER_GOOGLE_EMAIL", ME)


def sent_promise() -> Accounts:
    accounts = Accounts()
    accounts.mail(
        "m1", ME, "ravi@partner.example", "Q4 deck", "Sure, I will send the deck by Thursday 17:00."
    )
    return accounts


def test_a_promise_in_sent_mail_becomes_a_task_and_a_moved_date_holds_it():
    accounts = sent_promise()
    rt = run("auto", accounts)
    due = rt.store.beliefs("people", subject="promise-deck", predicate="promise.due")
    assert [(b.value, b.status) for b in due] == [
        ("2026-10-22T17:00", "retracted"),  # Ravi, whom the promise was made to, moved it
        ("2026-10-26T17:00", "active"),
    ]
    held = [e.data for e in rt.log.events if e.kind == "held"]
    assert held and held[0]["tool"] == "todoist_add-tasks"
    assert [t["dueString"] for t in accounts.tasks] == ["2026-10-22T17:00", "2026-10-26T17:00"]


def test_shadow_mode_records_what_the_team_would_do_and_runs_nothing():
    accounts = sent_promise()
    rt = run("shadow", accounts)
    book = list(approvals(rt).proposals.values())
    assert book and accounts.tasks == []
    assert any(p.status in ("held", "reviewed") for p in book)


def test_check_says_what_is_missing_without_starting_anything(tmp_path, monkeypatch, capsys):  # noqa: ANN001
    from graph_agent.packs.apps import run as apps_run

    monkeypatch.setattr(apps_run, "ROOT", tmp_path)  # no .env here
    for name in ("TODOIST_API_KEY", "GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "connections.json").write_text(json.dumps({"connections": [{"preset": "todoist"}]}))
    monkeypatch.setattr(apps_run, "TEAMS", tmp_path / "my-teams")
    (tmp_path / "my-teams").mkdir()
    bad = {"agents": [{"name": "Tasks", "job": "x"}]}
    (tmp_path / "my-teams" / "uni.json").write_text(json.dumps(bad))
    assert apps_run.check(None, tmp_path / "connections.json") == 1  # every team in the folder
    out = capsys.readouterr().out
    assert "not ready: set TODOIST_API_KEY in .env" in out
    assert "team uni:" in out and "agent 'Tasks': use a short lowercase name" in out
