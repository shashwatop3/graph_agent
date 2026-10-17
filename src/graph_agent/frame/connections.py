"""Connections: a person's own apps, described in a file instead of written as code.

A connection is one MCP server (its command, or its URL) and what the team may do with it. The
person lists theirs in a connections file, kept out of git, which names secrets only by their
name in `.env`:

    {"connections": [
      {"preset": "google"},                                   # a ready-made one (presets.py)
      {"preset": "todoist", "include": ["find-*", "add-tasks"]},   # ... with changes
      {"name": "notes", "command": "npx", "args": ["-y", "some-mcp-server"],
       "env": {"API_KEY": "$NOTES_KEY"},                      # the value comes from .env
       "outward": {"delete-*": true}}                         # gated, whatever the server says
    ]}

Its tools reach the nodes named "<connection>_<tool>" (google_get_events), so a node's spec can
allow one app's tools with "google_*". Whether a tool is gated: the server's read-only hint,
unless `outward` says otherwise; a tool the server does not mark read-only is gated (unknown means
gated). Secrets stay in the environment: the file, the team and the console only see their names.
A connection can instead be given one person's own secrets (`with_secrets`, for a console that
several people use): then their names are looked up there, and a server it starts gets those and
the few system variables it needs to run, not this process's environment.

A connection can also have feeds: tools polled every tick whose results come to the team as items
(see feeds.py).
"""

import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .mcp import MCPTools


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Feed(Strict):
    """A tool polled for news. With `ids`, its result lists items (a regex finds each one's id)
    and `open` reads each new one; without, the whole result is one item whenever it changes."""

    name: str  # the stream's name in the team ("mail")
    tool: str  # the tool to poll, as the server names it
    args: dict[str, Any] = Field(default_factory=dict[str, Any])  # "{today+30}": a date
    every: int = 1  # poll every this many ticks
    ids: str | None = None  # a regex with one group: the id of each item in the result
    open: str | None = None  # the tool that reads one item ...
    open_arg: str = "id"  # ... given its id as this argument
    newest_first: bool = True  # the result lists the newest first (items go to the team oldest
    # first, so a later item can correct an earlier one)
    sender: str | None = None  # a header line ("From") naming who sent each item
    me: str = ""  # the person's own address: what they sent comes from "me"
    # a system of record (the person's own calendar): its items are evidence, not hearsay
    trusted: bool = False
    sign_in: str | None = None  # a word in a result that means the server wants a sign-in first
    limit: int = 6000  # characters of each item kept


class Connection(Strict):
    name: str  # also the prefix of its tools, so: letters, digits, "-"
    label: str = ""
    about: str = ""  # one line for the console: what it is, what it needs
    command: str | None = None  # a local server, started for the run ("python": this Python)
    args: list[str] = Field(default_factory=list[str])
    env: dict[str, str] = Field(default_factory=dict[str, str])  # "$NAME": from the environment
    url: str | None = None  # a remote server (Streamable HTTP)
    headers: dict[str, str] = Field(default_factory=dict[str, str])  # e.g. a bearer token
    bind: dict[str, str] = Field(default_factory=dict[str, str])  # filled in, hidden from models
    include: list[str] | None = None  # the tools offered (patterns); None: all of them
    exclude: list[str] = Field(default_factory=list[str])
    outward: dict[str, bool] = Field(default_factory=dict[str, bool])  # tool pattern -> gated
    feeds: list[Feed] = Field(default_factory=list[Feed])
    timeout: float = 180.0
    _secrets: Mapping[str, str] | None = PrivateAttr(default=None)  # None: the environment

    @model_validator(mode="after")
    def _check(self) -> "Connection":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", self.name):
            raise ValueError(f"connection name {self.name!r}: use lowercase letters, digits, -")
        if (self.command is None) == (self.url is None):
            raise ValueError(f"connection {self.name}: give either a command or a url")
        return self

    @property
    def prefix(self) -> str:
        return f"{self.name}_"

    def _references(self) -> list[list[str]]:
        values = [*self.env.values(), *self.headers.values(), *self.bind.values(), self.url or ""]
        values += [feed.me for feed in self.feeds]
        return [names for value in values for names in _references(value)]

    def with_secrets(self, secrets: Mapping[str, str]) -> "Connection":
        """This connection, its "$NAMES" looked up in `secrets` instead of the environment."""
        given = self.model_copy()
        given._secrets = secrets
        return given

    def resolve(self, value: str) -> str:
        """`value` with every "$NAME" replaced by its secret."""
        return resolve(value, self._secrets)

    def secrets(self) -> list[str]:
        """The environment names its settings refer to ("$NAME", "${NAME}"; of "${A|B}", A)."""
        return sorted({names[0] for names in self._references()})

    def missing(self) -> list[str]:
        """The secrets not set in the environment (of "${A|B}", A, when neither is set)."""
        return sorted(
            {names[0] for names in self._references() if not _lookup(names, self._secrets)}
        )


# "$NAME", "${NAME}", or "${A|B}": the first of A and B that is set (a .env may already use
# another name for the same secret)
_NAME = re.compile(r"\$\{([A-Z_][A-Z0-9_]*(?:\|[A-Z_][A-Z0-9_]*)*)\}|\$([A-Z_][A-Z0-9_]*)")


def _references(value: str) -> list[list[str]]:
    return [(m.group(1) or m.group(2)).split("|") for m in _NAME.finditer(value)]


def _lookup(names: list[str], secrets: Mapping[str, str] | None = None) -> str:
    found = os.environ if secrets is None else secrets
    return next((found[n] for n in names if found.get(n)), "")


def resolve(value: str, secrets: Mapping[str, str] | None = None) -> str:
    """`value` with every "$NAME" replaced by its value in `secrets` (None: the environment)."""
    return _NAME.sub(lambda m: _lookup((m.group(1) or m.group(2)).split("|"), secrets), value)


# what a started server needs from this process to run at all, when it is given someone's own
# secrets instead of the environment (uvx and npx find themselves, their caches and a temp folder)
SYSTEM = (
    *("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR"),
    *("XDG_CACHE_HOME", "UV_CACHE_DIR", "UV_TOOL_DIR", "NPM_CONFIG_CACHE"),
)


def load_env(path: str | Path) -> None:
    """Read NAME=value lines from a .env file into the environment (set values win)."""
    env = Path(path)
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() and value.strip() and not line.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())


def from_entry(
    entry: dict[str, Any], presets: Mapping[str, dict[str, Any]] | None = None
) -> Connection:
    """One entry of a connections file: a preset (with changes), or a connection in full.
    `presets`: these instead of presets.PRESETS (a hosted console's own)."""
    from .presets import PRESETS

    presets = PRESETS if presets is None else presets
    entry = dict(entry)
    preset = entry.pop("preset", None)
    if preset is None:
        return Connection.model_validate(entry)
    if preset not in presets:
        raise ValueError(f"no preset {preset!r}; the presets are {', '.join(sorted(presets))}")
    return Connection.model_validate({"name": preset, **presets[preset], **entry})


def load_connections(
    path: str | Path, presets: Mapping[str, dict[str, Any]] | None = None
) -> list[Connection]:
    """The person's connections (none if the file does not exist yet)."""
    file = Path(path)
    if not file.exists():
        return []
    data = json.loads(file.read_text())
    connections = [from_entry(entry, presets) for entry in data.get("connections", [])]
    names = [c.name for c in connections]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise ValueError(f"connection names must be unique: {', '.join(twice)}")
    return connections


def server_of(connection: Connection) -> Any:
    """What the MCP client connects to: a started command, or a URL (with its headers)."""
    if connection.command is not None:
        from mcp import StdioServerParameters

        command = sys.executable if connection.command == "python" else connection.command
        own = {k: connection.resolve(v) for k, v in connection.env.items()}
        if connection._secrets is None:  # pyright: ignore[reportPrivateUsage]
            env = {**os.environ, **own}
        else:  # someone's own secrets: not this process's environment
            env = {**{k: os.environ[k] for k in SYSTEM if k in os.environ}, **own}
        return StdioServerParameters(command=command, args=list(connection.args), env=env)
    url = connection.resolve(connection.url or "")
    if not connection.headers:
        return url
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client  # pyright: ignore[reportPrivateUsage]

    headers = {k: connection.resolve(v) for k, v in connection.headers.items()}
    return streamable_http_client(url, http_client=create_mcp_http_client(headers=headers))


def connect(connection: Connection, server: Any = None) -> MCPTools:
    """Start (or reach) the connection's server and list its tools. `server`: connect to this
    instead (an in-process server, in tests). Raises ValueError naming any secret not set."""
    missing = connection.missing()
    if missing and server is None:
        raise ValueError(f"{connection.name}: set {', '.join(missing)} in .env")
    return MCPTools(
        server if server is not None else server_of(connection),
        prefix=connection.prefix,
        timeout=connection.timeout,
        bind={k: connection.resolve(v) for k, v in connection.bind.items()},
        include=connection.include,
        exclude=connection.exclude,
        outward=connection.outward,
    )


def tool_table(tools: MCPTools) -> list[dict[str, Any]]:
    """The connection's tools as the console lists them: name, what it does, whether gated."""
    return [
        {"name": t.name, "description": t.description, "outward": t.outward}
        for t in tools.list_tools()
    ]
