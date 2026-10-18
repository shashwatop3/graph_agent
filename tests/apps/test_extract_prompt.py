"""The router's own instructions to the reading model replace the template, and only when set."""

from types import SimpleNamespace
from typing import Any

from graph_agent.frame.nodes import RouterNode
from graph_agent.frame.runtime import Item
from graph_agent.frame.spec import NodeSpec
from graph_agent.harness.llm import ModelReply
from graph_agent.packs.apps.pack import EXTRACT_PROMPT, AppsPack


def reading(config: dict[str, Any]) -> list[str]:
    seen: list[str] = []

    class Client:
        def complete(self, system: str, messages: Any, tools: Any) -> ModelReply:
            seen.append(system)
            return ModelReply(text="{}")

    pack = AppsPack({"Event": ["starts"]}, [])
    log = SimpleNamespace(emit=lambda *a, **k: None)
    rt = SimpleNamespace(pack=pack, client=Client(), entities={}, log=log, tick=0)
    routed: list[Any] = []
    rt.route = lambda item, to, via=(): routed.append(to)  # type: ignore[attr-defined]
    rt.owners = lambda entity: []  # type: ignore[attr-defined]
    router = RouterNode(NodeSpec(id="router", type="router", config=config), rt)  # type: ignore[arg-type]
    router.receive(Item(id="i1", kind="email", tick=0, source="gmail", payload={"body": "hi"}))
    return seen


def test_template_by_default() -> None:
    assert reading({}) == [EXTRACT_PROMPT]


def test_the_routers_prompt_replaces_it() -> None:
    assert reading({"prompt": "Only flights."}) == ["Only flights."]


def test_a_teams_router_prompt_goes_to_its_router() -> None:
    from graph_agent.packs.apps.setup import Setup, team_of

    agents = [{"name": "reader", "job": "read"}]
    plain = team_of(Setup.model_validate({"agents": agents}), [])
    edited = team_of(Setup.model_validate({"agents": agents, "router_prompt": "Only flights."}), [])

    def router(team: object) -> dict[str, object]:
        return next(n for n in team.nodes if n.id == "router").config  # type: ignore[attr-defined]

    assert "prompt" not in router(plain)  # unset: the template
    assert router(edited)["prompt"] == "Only flights."
