"""Your own agents in the console: their team, the setup form's data, and a run on your apps.

Besides what every console pack gives, this one keeps setups the page edits as a form
(`setup_view`, `save_setup`, `delete_setup`): your teams, one file each in my-teams/, each turned
into a team by `team_of`. A team's id is its file's name, made from the name it was first saved
with; renaming a team later keeps its file.
"""

import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from graph_agent.core.store import Store
from graph_agent.frame.connections import Connection, load_connections, load_env
from graph_agent.frame.console import (
    Choice,
    PackCatalogue,
    Recorded,
    RunOption,
    Session,
    Template,
)
from graph_agent.frame.events import EventLog
from graph_agent.frame.nodes import approvals
from graph_agent.frame.spec import TeamSpec
from graph_agent.frame.streams import LiveStream, Stream
from graph_agent.harness.llm import ModelClient

from .pack import vocabulary
from .run import CONNECTIONS, EXAMPLES, ROOT, TEAMS, build_apps, load_setup
from .setup import Setup, problems, streams_of, team_of, things_of


class AppsConsole:
    name = "apps"
    title = "My apps: your own agents on your own accounts"
    cache_suffix = "-apps"
    options = [
        RunOption(
            "approvals",
            "Outward actions",
            [
                Choice("shadow", "Record only (never run)"),
                Choice("manual", "Wait for me"),
                Choice("auto", "Run at once"),
            ],
        )
    ]

    def __init__(
        self,
        teams_dir: Path = TEAMS,
        connections_file: Path = CONNECTIONS,
        secrets: Callable[[], Mapping[str, str]] | None = None,
        presets: Mapping[str, dict[str, Any]] | None = None,
        allow: Callable[[Stream], None] | None = None,
    ) -> None:
        # the repository's files and .env by default; a hosted console gives each person their
        # own files, their own keys (read again each time: they may have just added one), its
        # own presets (Google through one shared server) and a rule for streams (`allow` raises
        # ValueError for one it may not read)
        self.teams_dir = teams_dir
        self.connections_file = connections_file
        self.secrets = secrets
        self.presets = presets
        self.allow = allow

    def connections(self) -> list[Connection]:
        """Yours, from connections.json (their secrets from .env, or your own keys)."""
        if self.secrets is None:
            load_env(ROOT / ".env")
            return load_connections(self.connections_file)
        keys = self.secrets()
        found = load_connections(self.connections_file, self.presets)
        return [c.with_secrets(keys) for c in found]

    # ---- your teams ---------------------------------------------------------------------------

    def _file(self, team: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", team):
            raise ValueError(f"no team {team!r}")
        return self.teams_dir / f"{team}.json"

    def saved(self) -> list[str]:
        """Your teams' ids, in name order."""
        if not self.teams_dir.exists():
            return []
        return sorted(f.stem for f in self.teams_dir.glob("*.json"))

    def setup(self, name: str = "example") -> Setup:
        """One of your teams, or an example (one of EXAMPLES; a team not saved: "example")."""
        if name not in EXAMPLES and self._file(name).exists():
            return load_setup(self._file(name))
        return Setup.model_validate(EXAMPLES.get(name, EXAMPLES["example"]))

    def new_id(self, name: str) -> str:
        """A file name for a new team called `name`, not yet taken ("Uni deadlines" ->
        "uni-deadlines", then "uni-deadlines-2")."""
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "team"
        if base in EXAMPLES:  # an example's name is the example's, not a team's
            base = "my-team" if base == "example" else f"my-{base}"
        taken = set(self.saved())
        found, n = base, 2
        while found in taken:
            found, n = f"{base}-{n}", n + 1
        return found

    def templates(self) -> list[Template]:
        found: list[Template] = []
        for team in self.saved():
            setup = self.setup(team)
            found.append(Template(team, setup.name, f"Yours: {len(setup.agents)} agents"))
        found.append(
            Template("example", "Example: inbox, calendar, people, tasks", "A team to start from")
        )
        found.append(
            Template(
                "quake-desk",
                "Example: a quake desk on live public data",
                "Three agencies and the posts people make: no account needed",
            )
        )
        return found

    def team(self, name: str, options: dict[str, Any]) -> TeamSpec:
        return team_of(self.setup(name), self.connections())

    def catalogue(self) -> PackCatalogue:
        return PackCatalogue(predicates=vocabulary(things_of(self.setup())))

    def stand_in(self, team: TeamSpec) -> ModelClient:
        raise ValueError(
            "your own agents need a real model (there is no scripted stand-in for your mail): "
            "pick one under Model. Outward actions stay recorded only unless you choose otherwise"
        )

    def start(
        self,
        team: TeamSpec,
        client: ModelClient,
        store: Store,
        log: EventLog,
        options: dict[str, str],
    ) -> Session:
        if options.get("approvals") in ("auto", "manual", "shadow"):
            team.settings.approvals = options["approvals"]  # type: ignore[assignment]
        keys = self.secrets() if self.secrets is not None else None
        runtime, pack = build_apps(
            team, self.connections(), client, store, log, secrets=keys, allow=self.allow
        )

        def world() -> dict[str, Any]:
            seen = [e for e in runtime.log.events if e.kind == "item"]
            return {
                "lens": "apps",
                "approvals": runtime.settings.approvals,
                "feeds": sorted(runtime.feeds),
                "streams": [
                    {
                        "name": name,
                        "received": feed.received,
                        "kept": feed.kept,
                        "skipped": feed.skipped,
                        "error": feed.error,
                    }
                    for name, feed in sorted(runtime.feeds.items())
                    if isinstance(feed, LiveStream)
                ],
                "items": [
                    {
                        "id": e.data["item"],
                        "tick": e.tick,
                        "kind": e.data.get("item_kind"),
                        "from": e.data["source"],
                        "subject": str(
                            cast(dict[str, Any], e.data.get("payload") or {}).get("subject", "")
                        ),
                    }
                    for e in seen[-40:]
                ],
            }

        def score() -> dict[str, Any]:
            book = approvals(runtime).proposals.values()
            extracted = [e for e in runtime.log.events if e.kind == "extract"]
            return {
                "items": sum(1 for e in runtime.log.events if e.kind == "item"),
                "claims_read": sum(len(e.data.get("claims") or []) for e in extracted),
                "actions_proposed": len(book),
                "actions_held": sum(p.status in ("held", "reviewed") for p in book),
                "exposures": len(runtime.exposures),
                "tokens_in": sum(t.tokens_in for _, _, t in runtime.turns) + pack.extract_tokens[0],
            }

        return Session(runtime, world, score, pack.clock_label)

    def recorded(self) -> list[Recorded]:
        return []

    # ---- the setup form -----------------------------------------------------------------------

    def setup_view(self, team: str | None = None) -> dict[str, Any]:
        """Your teams, and one of them as the form shows it: `team` (one of EXAMPLES: that
        example), else your first, else the example (not saved: `team` is None in the answer).
        `examples` are the teams to start from."""
        teams = self.saved()
        example = "example"
        if team is None:
            team = teams[0] if teams else None
        elif team in EXAMPLES:
            team, example = None, team
        elif team not in teams:
            raise ValueError(f"no team {team!r}")
        setup = self.setup(team or example)
        return {
            "teams": [{"id": t, "name": self.setup(t).name} for t in teams],
            "examples": [{"id": e, "name": str(EXAMPLES[e]["name"])} for e in EXAMPLES],
            "team": team,
            "setup": setup.model_dump(mode="json"),
            "saved": team is not None,
            "kinds": things_of(setup),
            "problems": self._problems(setup),
        }

    def save_setup(
        self, data: dict[str, Any], write: bool = True, team: str | None = None
    ) -> dict[str, Any]:
        """Check the form's setup and (if it parses) save it as `team`, or as a new team when
        None. Says what is wrong with it, in plain words, and the team it was saved as.
        `write=False` only checks."""
        try:
            setup = Setup.model_validate(data)
        except ValidationError as error:
            wrong = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
            return {"problems": wrong, "team": team}
        if write:
            # an example is never saved over: saving it makes a team of your own
            team = team if team is not None and team not in EXAMPLES else self.new_id(setup.name)
            self.teams_dir.mkdir(parents=True, exist_ok=True)
            self._file(team).write_text(
                setup.model_dump_json(indent=2, exclude_defaults=True) + "\n"
            )
        return {"problems": self._problems(setup), "team": team}

    def _problems(self, setup: Setup) -> list[str]:
        """What is wrong with the setup, and (hosted) the streams it may not read."""
        found = problems(setup, self.connections())
        if self.allow is not None and not found:
            for stream in streams_of(setup.streams):
                try:
                    self.allow(stream)
                except ValueError as error:
                    found.append(str(error))
        return found

    def delete_setup(self, team: str) -> None:
        file = self._file(team)
        if not file.exists():
            raise ValueError(f"no team {team!r}")
        file.unlink()


APPS = AppsConsole()
