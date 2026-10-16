"""Record a finished game as plain JSON, and write the viewer page that plays it back.

The replay holds what a viewer needs and nothing it has to recompute: the ring, the paths fire can
take, and for every day the fires that started, the messages sent (with their true route and
whether an imposter altered them), the shortcut links built, the waterings, and each correction
with the beliefs it changed. The viewer is a single static HTML file with the replay embedded, so
it opens by double-click and needs no server.
"""

import json
from pathlib import Path

from ..adapters import ringfire
from .game import GameResult, run_game
from .scoring import score_game

TEMPLATE = Path(__file__).resolve().parents[3] / "viewer" / "template.html"


def _claim_text(backend, viewer: str, change) -> str:
    """What a changed belief said, in words. Falls back to its id when there is no store."""
    store = getattr(backend, "store", None)
    belief = store.get(viewer, change.belief_id) if store is not None else None
    if belief is None:
        return change.belief_id
    template = ringfire.TEMPLATES.get(belief.predicate, "{predicate}({subject}) = {value}")
    return template.format(
        subject=belief.subject,
        value=belief.value,
        unit=belief.unit or "",
        predicate=belief.predicate,
    )


def build_replay(result: GameResult, backend, links_added: dict[int, list], score: dict) -> dict:
    game = result.game
    world = game.sim.world
    watered: dict[int, list[int]] = {}
    for day, agent, turn in result.turns:
        if any(
            name == "act" and out.endswith("you will water your fields today")
            for name, _, out in turn.calls
        ):
            watered.setdefault(day, []).append(int(agent[1:]))

    days = []
    for day_result in result.days:
        day = day_result.report.day
        days.append(
            {
                "day": day,
                "ignited": [
                    {"field": e.field_id, "intensity": e.intensity, "audience": list(e.audience)}
                    for e in day_result.evidence
                ],
                "via_hidden": [[e.src, e.dst] for e in day_result.report.revealed_hidden],
                "burnt_out": list(day_result.report.burnt_out),
                "watered": sorted(watered.get(day, [])),
                "links_added": links_added.get(day, []),
                "messages": [
                    {
                        "sender": m.sender,
                        "receiver": m.receiver,
                        "route": list(m.route),
                        "field": m.claim.field_id,
                        "claim_day": m.claim.day,
                        "altered_by": list(m.altered_by),
                    }
                    for m in game.net.log
                    if m.day == day
                ],
                "exposures": [
                    {
                        "viewer": int(e.viewer[1:]),
                        "agent": int(e.agent[1:]),
                        "reason": e.reason,
                        "changes": [
                            {
                                "belief": c.belief_id,
                                "status": c.new_status,
                                "path": c.path_len,
                                "text": _claim_text(backend, e.viewer, c),
                            }
                            for c in e.changes
                        ],
                    }
                    for e in backend.exposures
                    if e.day == day
                ],
            }
        )
    return {
        "system": backend.name,
        "n_agents": world.config.n_agents,
        "fields": [{"id": f, "owner": world.owner(f)} for f in range(world.n_fields)],
        "edges": [
            {"src": e.src, "dst": e.dst, "weight": e.weight, "hidden": e.hidden}
            for e in world.edges
        ],
        "imposters": {str(a): b.value for a, b in game.net.imposters.items()},
        "start_links": [sorted(link) for link in game.net.links],
        "days": days,
        "score": score,
    }


def record_replay(scenario: dict, backend, client, **run_kwargs) -> dict:
    """Play the scenario on `backend` with `client` and return the replay."""
    links_added: dict[int, list] = {}
    n = scenario["world"]["n_agents"]
    # the links the game starts with: the ring, plus any the scenario lists
    seen = {frozenset((a, (a + 1) % n)) for a in range(n)}
    seen |= {frozenset(link) for link in scenario.get("links", [])}

    def note_new_links(game, _backend, day: int) -> None:
        fresh = sorted(sorted(link) for link in game.net.links - seen)
        if fresh:
            links_added[day] = fresh
            seen.update(game.net.links)

    result = run_game(scenario, backend, client, after_day=note_new_links, **run_kwargs)
    return build_replay(result, backend, links_added, score_game(result, backend))


def write_viewer(replay: dict, path: str | Path) -> Path:
    """A self-contained HTML page that plays `replay` back."""
    html = TEMPLATE.read_text().replace("__REPLAY__", json.dumps(replay).replace("</", "<\\/"))
    out = Path(path)
    out.write_text(html)
    return out
