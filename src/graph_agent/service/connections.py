"""The API for your apps and your agents: the console's "My apps" page.

    GET  /api/connections              the presets, and your connections with what each still needs
    PUT  /api/connections              save them (connections.json)   {connections: [...]}
    POST /api/connections/test         start one, list its tools, read each feed once
    GET  /api/packs/{pack}/setup?team=  a pack's setup form (one of your teams), with its problems
    PUT  /api/packs/{pack}/setup?team=  save it (no team: as a new one);  POST .../setup/check
    DELETE /api/packs/{pack}/setup?team=  delete that team
    GET /api/keys, PUT|DELETE /api/keys/{NAME}   hosted only: your keys (values never sent back)

A connection names its secrets ("$TODOIST_API_KEY"). Locally you put the values in .env, and what
writes a file or starts a server's command is refused unless the request comes from this console
itself, on this machine: a page on another site (or a DNS name rebound to 127.0.0.1) cannot send
them. Hosted, each person keeps their own keys here (users.py stores them encrypted), and may only
use the presets (whose commands are ours) or apps on the public internet (an https URL): nobody
starts a command of their own on the server.
"""

import ipaddress
import json
import re
import socket
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from ..frame.connections import Connection, connect, from_entry, load_env, tool_table
from ..frame.feeds import ConnectionFeed, NeedsSignIn
from ..frame.presets import PRESETS
from .auth import ACCESS, RESERVED, current_user, google_connected, hosted_presets, keys_for
from .registry import pack_named
from .spaces import ROOT
from .users import LOCAL as LOCAL_USER
from .users import User, delete_secret, hosted, save_secret, secret_names

CONNECTIONS = ROOT / "connections.json"  # the local person's; hosted, each has one in their folder
LOCAL = {"127.0.0.1", "localhost", "::1"}


def local_only(request: Request) -> None:
    if hosted():  # the page is not on this machine: auth.guard checks who asks, and from where
        return
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


def connections_file(user: User) -> Path:
    return CONNECTIONS if user.id == "local" else user.folder / "connections.json"


def read_entries(file: Path) -> list[dict[str, Any]]:
    if not file.exists():
        return []
    data = cast(dict[str, Any], json.loads(file.read_text()))
    return list(data.get("connections", []))


def presets() -> dict[str, dict[str, Any]]:
    return hosted_presets() if hosted() else PRESETS


def parse(entries: list[dict[str, Any]], user: User = LOCAL_USER) -> list[Connection]:
    """The connections, refused (400) with the reason if one is not valid, or (hosted) not one a
    person may add; hosted, each one looks its secrets up in the person's own keys."""
    try:
        found = [from_entry(e, presets()) for e in entries]
    except (ValidationError, ValueError) as error:
        raise HTTPException(400, str(error)) from error
    names = [c.name for c in found]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise HTTPException(400, f"connection names must be unique: {', '.join(twice)}")
    if not hosted():
        return found
    keys = keys_for(user)
    found = [c.with_secrets(keys) for c in found]
    for entry, connection in zip(entries, found, strict=True):
        hosted_rules(entry, connection)
    return found


# hosted: what a person may change in a preset (not its command, args or env: those are ours), and
# what an app of their own may say (a server on the internet: no command, args or env)
PRESET_CHANGES = {"preset", "label", "include", "exclude", "outward"}
REMOTE = set("name label about url headers bind include exclude outward feeds timeout".split())


def hosted_rules(entry: dict[str, Any], connection: Connection) -> None:
    if "preset" in entry:
        changed = sorted(set(entry) - PRESET_CHANGES)
        if changed:
            what = ", ".join(changed)
            raise HTTPException(400, f"{connection.name}: here a preset's {what} cannot change")
        return
    if connection.command is not None or set(entry) - REMOTE:
        raise HTTPException(
            400,
            f"{connection.name}: here an app is a server on the internet (an https URL), not a "
            "command to start on this machine",
        )
    public_https(connection.name, connection.resolve(connection.url or ""))


def public_https(name: str, url: str) -> None:
    """Refuse a URL that is not https, or whose host is not on the public internet: this server's
    own address, its network, or the cloud's metadata service are not anyone's app."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise HTTPException(400, f"{name}: the url must start with https://")
    try:
        found = socket.getaddrinfo(parsed.hostname, parsed.port or 443, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError) as error:
        raise HTTPException(400, f"{name}: no such host {parsed.hostname}") from error
    addresses = {str(info[4][0]).split("%")[0] for info in found}
    if not all(ipaddress.ip_address(a).is_global for a in addresses):
        raise HTTPException(400, f"{name}: {parsed.hostname} is not on the public internet")


def needs(missing: list[str]) -> str:
    """What to do about secrets not set, in the words of where they are kept."""
    if not hosted():
        return f"set {', '.join(missing)} in .env"
    if ACCESS in missing:
        return "connect your Google account under Your keys"
    return f"add {', '.join(missing)} under Your keys"


def setup_pack(name: str, user: User) -> Any:
    try:
        pack = pack_named(name, user)
    except ValueError as error:
        raise HTTPException(404, str(error)) from error
    if not hasattr(pack, "setup_view"):
        raise HTTPException(404, f"the {name} pack has no setup form")
    return pack


def router() -> APIRouter:
    api = APIRouter()
    You = Depends(current_user)  # the person asking (the local one, when not hosted)

    @api.get("/api/connections")
    def connections(user: User = You) -> dict[str, Any]:
        load_env(ROOT / ".env")
        entries = read_entries(connections_file(user))
        return {
            "presets": [
                {"name": name, "label": p.get("label", name), "about": p.get("about", "")}
                for name, p in presets().items()
            ],
            "entries": entries,
            "connections": [describe(c) for c in parse(entries, user)],
        }

    @api.put("/api/connections", dependencies=[Depends(local_only)])
    def save(body: Entries, user: User = You) -> dict[str, Any]:
        found = parse(body.connections, user)
        file = connections_file(user)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"connections": body.connections}, indent=2) + "\n")
        load_env(ROOT / ".env")
        return {"connections": [describe(c) for c in found]}

    @api.post("/api/connections/test", dependencies=[Depends(local_only)])
    def test(entry: dict[str, Any], user: User = You) -> dict[str, Any]:
        """Start the connection, list its tools, read each feed once. Never raises for what the
        server does: the answer says what went wrong (or the sign-in link it asked for)."""
        load_env(ROOT / ".env")
        (connection,) = parse([entry], user)
        if connection.missing():
            return {"ok": False, "error": needs(connection.missing())}
        try:
            tools = connect(connection)
        except (RuntimeError, ValueError, OSError) as error:
            return {"ok": False, "error": f"could not start it: {error}"}
        try:
            feeds: list[dict[str, Any]] = []
            for feed in connection.feeds:
                try:
                    items = ConnectionFeed(tools, feed, me=connection.resolve(feed.me))(0)
                    subjects = [str(i.payload.get("subject", "")) for i in items[:3]]
                    feeds.append({"name": feed.name, "items": len(items), "sample": subjects})
                except NeedsSignIn as error:
                    link = re.search(r"https?://\S+", str(error))
                    sign_in = link.group(0) if link else str(error)
                    if hosted():  # the sign-in is ours there: connecting the Google account again
                        sign_in = "/auth/google"
                    feeds.append({"name": feed.name, "sign_in": sign_in})
                except (ValueError, TimeoutError) as error:
                    feeds.append({"name": feed.name, "error": str(error)[:300]})
            return {"ok": True, "tools": tool_table(tools), "feeds": feeds}
        finally:
            tools.close()

    # ---- a pack's setup form --------------------------------------------------------------------

    @api.get("/api/packs/{pack}/setup")
    def setup(pack: str, team: str | None = None, user: User = You) -> dict[str, Any]:
        try:
            return setup_pack(pack, user).setup_view(team)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @api.put("/api/packs/{pack}/setup", dependencies=[Depends(local_only)])
    def save_setup(
        pack: str, data: dict[str, Any], team: str | None = None, user: User = You
    ) -> dict[str, Any]:
        try:
            return setup_pack(pack, user).save_setup(data, write=True, team=team)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error

    @api.post("/api/packs/{pack}/setup/check")
    def check_setup(pack: str, data: dict[str, Any], user: User = You) -> dict[str, Any]:
        return setup_pack(pack, user).save_setup(data, write=False)

    @api.delete("/api/packs/{pack}/setup", dependencies=[Depends(local_only)])
    def delete_setup(pack: str, team: str, user: User = You) -> dict[str, Any]:
        try:
            setup_pack(pack, user).delete_setup(team)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error
        return {"deleted": team}

    # ---- your keys (hosted) ---------------------------------------------------------------------

    class Key(BaseModel):
        value: str

    def hosted_or_404() -> None:
        if not hosted():
            raise HTTPException(404, "keys are kept in .env on this machine")

    @api.get("/api/keys")
    def keys(user: User = You) -> dict[str, Any]:
        """The names of your keys, and of those your apps or a real model want (no values)."""
        hosted_or_404()
        wanted = {"ANTHROPIC_API_KEY"}
        for connection in parse(read_entries(connections_file(user)), user):
            wanted |= set(connection.secrets())
        saved = [n for n in secret_names(user) if n not in RESERVED]
        # the address you signed in with, and the Google token (connected, not pasted)
        wanted -= RESERVED
        return {"saved": saved, "wanted": sorted(wanted), "google": google_connected(user)}

    @api.put("/api/keys/{name}")
    def save_key(name: str, body: Key, user: User = You) -> dict[str, Any]:
        hosted_or_404()
        if name in RESERVED:
            raise HTTPException(400, f"{name} comes from signing in with Google, not from here")
        try:
            save_secret(user, name, body.value)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return {"saved": [n for n in secret_names(user) if n not in RESERVED]}

    @api.delete("/api/keys/{name}")
    def delete_key(name: str, user: User = You) -> dict[str, Any]:
        hosted_or_404()
        if name in RESERVED:
            raise HTTPException(400, f"{name} comes from signing in with Google, not from here")
        delete_secret(user, name)
        return {"saved": [n for n in secret_names(user) if n not in RESERVED]}

    return api
