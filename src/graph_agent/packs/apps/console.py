"""Your own agents in the console: their team, the setup form's data, and a run on your apps.

Besides what every console pack gives, this one keeps a setup the page edits as a form
(`setup_view`, `save_setup`): the agents file (agents.json) that `team_of` turns into a team.
"""

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
from .run import AGENTS, CONNECTIONS, EXAMPLE_AGENTS, ROOT, build_apps, load_setup
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

    def __init__(self) -> None:
        self.agents_file = AGENTS
        self.connections_file = CONNECTIONS

    def connections(self) -> list[Connection]:
        """Yours, from connections.json (their secrets from .env)."""
        load_env(ROOT / ".env")
        return load_connections(self.connections_file)

    def setup(self, name: str = "mine") -> Setup:
        if name == "mine" and self.agents_file.exists():
            return load_setup(self.agents_file)
        return Setup.model_validate(EXAMPLE_AGENTS)

    def templates(self) -> list[Template]:
        found = [
            Template("example", "Example: inbox, calendar, people, tasks", "A team to start from")
        ]
        if self.agents_file.exists():
            mine = load_setup(self.agents_file)
            found.insert(
                0, Template("mine", mine.name, f"Your agents.json: {len(mine.agents)} agents")
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

    def setup_view(self) -> dict[str, Any]:
        """The agents file as the form shows it (the example until one is saved)."""
        setup = self.setup()
        return {
            "setup": setup.model_dump(mode="json"),
            "saved": self.agents_file.exists(),
            "kinds": things_of(setup),
            "problems": problems(setup, self.connections()),
        }

    def save_setup(self, data: dict[str, Any], write: bool = True) -> list[str]:
        """Check the form's setup and (if it parses) write it to agents.json; what is wrong with
        it, in plain words. `write=False` only checks."""
        try:
            setup = Setup.model_validate(data)
        except ValidationError as error:
            return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
        if write:
            self.agents_file.write_text(
                setup.model_dump_json(indent=2, exclude_defaults=True) + "\n"
            )
        return problems(setup, self.connections())


APPS = AppsConsole()
