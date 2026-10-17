"""Your own agents in the console: their team, the setup form's data, and a run on your apps.

Besides what every console pack gives, this one keeps setups the page edits as a form
(`setup_view`, `save_setup`, `delete_setup`): your teams, one file each in my-teams/, each turned
into a team by `team_of`. A team's id is its file's name, made from the name it was first saved
with; renaming a team later keeps its file.
"""

import re
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
from graph_agent.harness.llm import ModelClient

from .pack import vocabulary
from .run import CONNECTIONS, EXAMPLE_AGENTS, ROOT, TEAMS, build_apps, load_setup
from .setup import Setup, problems, team_of, things_of


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

    def __init__(self, teams_dir: Path = TEAMS, connections_file: Path = CONNECTIONS) -> None:
        # the repository's files by default; a hosted console gives each person their own
        self.teams_dir = teams_dir
        self.connections_file = connections_file

    def connections(self) -> list[Connection]:
        """Yours, from connections.json (their secrets from .env)."""
        load_env(ROOT / ".env")
        return load_connections(self.connections_file)

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
        """One of your teams, or the example ("example", or a team not saved)."""
        if name != "example" and self._file(name).exists():
            return load_setup(self._file(name))
        return Setup.model_validate(EXAMPLE_AGENTS)

    def new_id(self, name: str) -> str:
        """A file name for a new team called `name`, not yet taken ("Uni deadlines" ->
        "uni-deadlines", then "uni-deadlines-2")."""
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "team"
        base = "my-team" if base == "example" else base
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
        runtime, pack = build_apps(team, self.connections(), client, store, log)

        def world() -> dict[str, Any]:
            seen = [e for e in runtime.log.events if e.kind == "item"]
            return {
                "lens": "apps",
                "approvals": runtime.settings.approvals,
                "feeds": sorted(runtime.feeds),
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
        """Your teams, and one of them as the form shows it: `team` ("example": the example),
        else your first, else the example (not saved: `team` is None in the answer)."""
        teams = self.saved()
        if team is None:
            team = teams[0] if teams else None
        elif team == "example":
            team = None
        elif team not in teams:
            raise ValueError(f"no team {team!r}")
        setup = self.setup(team or "example")
        return {
            "teams": [{"id": t, "name": self.setup(t).name} for t in teams],
            "team": team,
            "setup": setup.model_dump(mode="json"),
            "saved": team is not None,
            "kinds": things_of(setup),
            "problems": problems(setup, self.connections()),
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
            # the example is never saved over: saving it makes a team of your own
            team = team if team not in (None, "example") else self.new_id(setup.name)
            self.teams_dir.mkdir(parents=True, exist_ok=True)
            self._file(team).write_text(
                setup.model_dump_json(indent=2, exclude_defaults=True) + "\n"
            )
        return {"problems": problems(setup, self.connections()), "team": team}

    def delete_setup(self, team: str) -> None:
        file = self._file(team)
        if not file.exists():
            raise ValueError(f"no team {team!r}")
        file.unlink()


APPS = AppsConsole()
