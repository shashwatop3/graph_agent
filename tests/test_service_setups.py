"""The console's front page offers three ready-made setups (viewer/console/src/setups/content.ts):
each must name a template the service has, and the free ones must have a stand-in."""

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("mcp")

from fastapi.testclient import TestClient  # noqa: E402

from graph_agent.service.app import create_app  # noqa: E402

CONTENT = Path(__file__).parents[1] / "viewer" / "console" / "src" / "setups" / "content.ts"


def setups() -> list[tuple[str, str, bool]]:
    """(pack, template, offers the free stand-in) for each setup the page lists."""
    text = CONTENT.read_text()
    blocks = text.split("\n  {\n")[1:]
    found = []
    for block in blocks:
        pack = re.search(r'pack: "([\w-]+)"', block)
        template = re.search(r'template: "([\w-]+)"', block)
        assert pack and template, block[:200]
        found.append((pack.group(1), template.group(1), "STAND_IN" in block.split("models:")[1]))
    return found


def test_the_page_offers_three_setups():
    assert [p for p, _, _ in setups()] == ["apps", "ringfire", "offsite"]


@pytest.mark.parametrize(("pack", "template", "free"), setups())
def test_each_setup_is_a_template_the_service_has(pack: str, template: str, free: bool):
    client = TestClient(create_app(), base_url="http://127.0.0.1:8765")
    team = client.get(f"/api/templates/{pack}/{template}")
    assert team.status_code == 200, team.text
    assert team.json()["nodes"]
    if free:  # the free stand-in plays it
        from graph_agent.frame.spec import TeamSpec
        from graph_agent.service.registry import pack_named

        pack_named(pack).stand_in(TeamSpec.model_validate(team.json()))
