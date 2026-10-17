"""Connections: a person's apps described in a file, turned into the nodes' tools."""

import json
import sys

import pytest

pytest.importorskip("mcp")

from graph_agent.frame.connections import (  # noqa: E402
    Connection,
    connect,
    from_entry,
    load_connections,
    resolve,
    server_of,
    tool_table,
)
from graph_agent.packs.life.mcp_server import life_server  # noqa: E402
from graph_agent.packs.life.world import LifeWorld  # noqa: E402


def test_a_preset_with_changes(monkeypatch: pytest.MonkeyPatch):
    todoist = from_entry({"preset": "todoist", "include": ["find-tasks"]})
    assert todoist.name == "todoist" and todoist.command == "npx"
    assert todoist.include == ["find-tasks"]  # the change wins
    assert todoist.secrets() == ["TODOIST_API_KEY"]
    monkeypatch.delenv("TODOIST_API_KEY", raising=False)
    assert todoist.missing() == ["TODOIST_API_KEY"]
    monkeypatch.setenv("TODOIST_API_KEY", "x")
    assert todoist.missing() == []


def test_the_google_preset_names_every_secret_it_needs():
    google = from_entry({"preset": "google"})
    assert google.secrets() == [
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "USER_GOOGLE_EMAIL",
    ]
    assert [f.name for f in google.feeds] == ["mail", "calendar"]
    assert google.feeds[1].trusted and not google.feeds[0].trusted


def test_a_bad_file_says_what_is_wrong(tmp_path):  # noqa: ANN001
    with pytest.raises(ValueError, match="no preset 'gmial'"):
        from_entry({"preset": "gmial"})
    with pytest.raises(ValueError, match="either a command or a url"):
        Connection(name="x")
    with pytest.raises(ValueError, match="lowercase"):
        Connection(name="My App", command="x")
    file = tmp_path / "connections.json"
    file.write_text(json.dumps({"connections": [{"preset": "todoist"}, {"preset": "todoist"}]}))
    with pytest.raises(ValueError, match="unique: todoist"):
        load_connections(file)
    assert load_connections(tmp_path / "none.json") == []


def test_secrets_come_from_the_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOTES_KEY", "s3cret")
    assert resolve("Bearer $NOTES_KEY") == "Bearer s3cret"
    assert resolve("Bearer ${NOTES_KEY}!") == "Bearer s3cret!"
    notes = Connection(name="notes", command="python", args=["-m", "x"], env={"K": "$NOTES_KEY"})
    started = server_of(notes)
    assert started.command == sys.executable  # "python" is this Python
    assert started.env["K"] == "s3cret"
    assert server_of(Connection(name="web", url="https://x.example/mcp")) == (
        "https://x.example/mcp"
    )


def test_a_connection_refuses_to_start_without_its_secrets(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TODOIST_API_KEY", raising=False)
    with pytest.raises(ValueError, match="set TODOIST_API_KEY in .env"):
        connect(from_entry({"preset": "todoist"}))


def test_its_tools_are_named_after_it_and_gated_by_the_servers_hints():
    life = Connection(name="sim", command="unused", include=["mail_*", "calendar_list"])
    tools = connect(life, server=life_server(LifeWorld()))
    try:
        table = {t["name"]: t["outward"] for t in tool_table(tools)}
        assert table == {
            "sim_mail_search": False,
            "sim_mail_read": False,
            "sim_mail_send": True,
            "sim_calendar_list": False,
        }
        assert tools.call("mail_search", {"query": ""}) == "[]"  # by the server's own name
    finally:
        tools.close()


def test_the_person_can_gate_a_tool_or_free_one():
    life = Connection(
        name="sim",
        command="unused",
        include=["mail_*"],
        outward={"mail_search": True, "mail_send": False},
    )
    tools = connect(life, server=life_server(LifeWorld()))
    try:
        table = {t["name"]: t["outward"] for t in tool_table(tools)}
        assert table == {"sim_mail_search": True, "sim_mail_read": False, "sim_mail_send": False}
    finally:
        tools.close()
