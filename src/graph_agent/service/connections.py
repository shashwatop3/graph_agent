"""The API for your apps and your agents: the console's "My apps" page.

    GET  /api/connections              the presets, and your connections with what each still needs
    PUT  /api/connections              save them (connections.json)   {connections: [...]}
    POST /api/connections/test         start one, list its tools, read each feed once
    GET  /api/packs/{pack}/setup?team=  a pack's setup form (one of your teams), with its problems
    PUT  /api/packs/{pack}/setup?team=  save it (no team: as a new one);  POST .../setup/check
    DELETE /api/packs/{pack}/setup?team=  delete that team

Secrets never pass through here: a connection names them ("$TODOIST_API_KEY") and you put the
values in .env. What writes a file or starts a server's command is refused unless the request
comes from this console itself, on this machine: a page on another site (or a DNS name rebound to
127.0.0.1) cannot send them.
"""

import json
import re
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from ..frame.connections import Connection, connect, from_entry, load_env, tool_table
from ..frame.feeds import ConnectionFeed, NeedsSignIn
from ..frame.presets import PRESETS
from .registry import pack_named
from .spaces import ROOT

CONNECTIONS = ROOT / "connections.json"
LOCAL = {"127.0.0.1", "localhost", "::1"}


def local_only(request: Request) -> None:
    host = request.headers.get("host", "")
    hostname = urlparse(f"//{host}").hostname or ""
    if hostname not in LOCAL:
        raise HTTPException(403, "only from the console on this machine (127.0.0.1)")
    origin = request.headers.get("origin")
    if origin is not None and urlparse(origin).netloc != host:
        raise HTTPException(403, f"not from this console: {origin}")


class Entries(BaseModel):
    connections: list[dict[str, Any]]


def describe(connection: Connection) -> dict[str, Any]:
    return {
        "name": connection.name,
        "label": connection.label,
        "about": connection.about,
        "secrets": connection.secrets(),
        "missing": connection.missing(),
        "feeds": [f.name for f in connection.feeds],
        "include": connection.include,
        "outward": connection.outward,
    }


def read_entries() -> list[dict[str, Any]]:
    if not CONNECTIONS.exists():
        return []
    data = cast(dict[str, Any], json.loads(CONNECTIONS.read_text()))
    return list(data.get("connections", []))


def parse(entries: list[dict[str, Any]]) -> list[Connection]:
    try:
        found = [from_entry(e) for e in entries]
    except (ValidationError, ValueError) as error:
        raise HTTPException(400, str(error)) from error
    names = [c.name for c in found]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise HTTPException(400, f"connection names must be unique: {', '.join(twice)}")
    return found


def setup_pack(name: str) -> Any:
    try:
        pack = pack_named(name)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    if not hasattr(pack, "setup_view"):
        raise HTTPException(404, f"the {name} pack has no setup form")
    return pack


def router() -> APIRouter:
    api = APIRouter()

    @api.get("/api/connections")
    def connections() -> dict[str, Any]:
        load_env(ROOT / ".env")
        entries = read_entries()
        return {
            "presets": [
                {"name": name, "label": p.get("label", name), "about": p.get("about", "")}
                for name, p in PRESETS.items()
            ],
            "entries": entries,
            "connections": [describe(c) for c in parse(entries)],
        }

    @api.put("/api/connections", dependencies=[Depends(local_only)])
    def save(body: Entries) -> dict[str, Any]:
        found = parse(body.connections)
        CONNECTIONS.write_text(json.dumps({"connections": body.connections}, indent=2) + "\n")
        load_env(ROOT / ".env")
        return {"connections": [describe(c) for c in found]}

    @api.post("/api/connections/test", dependencies=[Depends(local_only)])
    def test(entry: dict[str, Any]) -> dict[str, Any]:
        """Start the connection, list its tools, read each feed once. Never raises for what the
        server does: the answer says what went wrong (or the sign-in link it asked for)."""
        load_env(ROOT / ".env")
        (connection,) = parse([entry])
        if connection.missing():
            return {"ok": False, "error": f"set {', '.join(connection.missing())} in .env"}
        try:
            tools = connect(connection)
        except (RuntimeError, ValueError, OSError) as error:
            return {"ok": False, "error": f"could not start it: {error}"}
        try:
            feeds: list[dict[str, Any]] = []
            for feed in connection.feeds:
                try:
                    items = ConnectionFeed(tools, feed)(0)
                    subjects = [str(i.payload.get("subject", "")) for i in items[:3]]
                    feeds.append({"name": feed.name, "items": len(items), "sample": subjects})
                except NeedsSignIn as error:
                    link = re.search(r"https?://\S+", str(error))
                    feeds.append(
                        {"name": feed.name, "sign_in": link.group(0) if link else str(error)}
                    )
                except (ValueError, TimeoutError) as error:
                    feeds.append({"name": feed.name, "error": str(error)[:300]})
            return {"ok": True, "tools": tool_table(tools), "feeds": feeds}
        finally:
            tools.close()

    # ---- a pack's setup form --------------------------------------------------------------------

    @api.get("/api/packs/{pack}/setup")
    def setup(pack: str, team: str | None = None) -> dict[str, Any]:
        try:
            return setup_pack(pack).setup_view(team)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @api.put("/api/packs/{pack}/setup", dependencies=[Depends(local_only)])
    def save_setup(pack: str, data: dict[str, Any], team: str | None = None) -> dict[str, Any]:
        try:
            return setup_pack(pack).save_setup(data, write=True, team=team)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @api.post("/api/packs/{pack}/setup/check")
    def check_setup(pack: str, data: dict[str, Any]) -> dict[str, Any]:
        return setup_pack(pack).save_setup(data, write=False)

    @api.delete("/api/packs/{pack}/setup", dependencies=[Depends(local_only)])
    def delete_setup(pack: str, team: str) -> dict[str, Any]:
        try:
            setup_pack(pack).delete_setup(team)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        return {"deleted": team}

    return api
