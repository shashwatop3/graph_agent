"""Compiles one agent's context window from the store, fresh every turn.

The store is the memory. What the model reads is only a view of it, rebuilt each turn, so a belief
that was corrected simply is not shown as current any more: there is nothing stale to clear out.

Sections, in order
  Role          who you are and the rules (supplied by the adapter)
  Commitments   actions in force, each flagged if it depends on a belief that is no longer sound
  Changes       what a correction changed since last turn, as tombstones. Always included.
  Inbox         what arrived since last turn
  Beliefs       the viewer's live beliefs, ranked by how close they are to what is happening now
  Notes         short notes the agent left itself

Everything is read through the Store interface with the viewer's id, so an agent can never be shown
anything it does not hold. The text is the same whichever store backs it.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .model import Belief
from .store import Change, Store

# Used when the adapter gives no template for a predicate.
DEFAULT_TEMPLATE = "{predicate}({subject}) = {value}"

_LIVE = ("active", "suspect")


def estimate_tokens(text: str) -> int:
    """About 4 characters per token. Rough, but enough to hold a budget; swap in a real tokenizer
    if exact counts ever matter."""
    return (len(text) + 3) // 4


def render_belief(belief: Belief, routes: list[tuple[str, ...]], templates: Mapping[str, str]):
    """One line: [id status routes confidence] what it says, and the route it came by."""
    template = templates.get(belief.predicate, DEFAULT_TEMPLATE)
    claim = template.format(
        subject=belief.subject,
        value=belief.value,
        unit=belief.unit or "",
        predicate=belief.predicate,
    )
    # an empty route means the agent saw it itself (a sensor reading or published evidence)
    shown = [f"via {'>'.join(route)}" if route else "seen directly" for route in routes[:2]]
    via = f"   {' | '.join(shown)}" if shown else "   derived by you"
    flags = f"{belief.id} {belief.status} routes {len(routes)} conf {belief.confidence:.2g}"
    return f"[{flags}] {claim}{via}"


def _tombstone(change: Change, belief: Belief | None, templates: Mapping[str, str]) -> str:
    claim = (
        templates.get(belief.predicate, DEFAULT_TEMPLATE).format(
            subject=belief.subject,
            value=belief.value,
            unit=belief.unit or "",
            predicate=belief.predicate,
        )
        if belief
        else "(belief not visible)"
    )
    cause = f"{change.correction_type} of {change.target}"
    if change.reason:
        cause += f" ({change.reason})"
    if change.new_status == "suspect":
        meaning = f"depends on something that changed, {change.path_len - 1} step(s) from the cause"
    elif change.new_status == "retracted":
        meaning = "you withdrew it"
    else:
        meaning = "lost all its support"
    return f"[{change.belief_id} {change.new_status.upper()}] {claim}   {meaning}: {cause}"


def _commitments(store: Store, viewer: str) -> list[str]:
    lines: list[str] = []
    for status in ("planned", "committed"):
        for action in store.actions(viewer, status=status):
            parts = [action.id, action.type]
            if action.target:
                parts.append(action.target)
            if action.params:
                parts.append(_compact(action.params, 80))
            line = f"- {' '.join(parts)} [{action.status}]"
            for source_id in store.sources(viewer, action.id):
                source = store.get(viewer, source_id)
                if isinstance(source, Belief) and source.status != "active":
                    line += f"\n    ! depends on {source.id}, which is {source.status}"
            lines.append(line)
    return lines


def _compact(payload: dict[str, Any], limit: int = 160) -> str:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fit(lines: Sequence[str], budget_tokens: int, keep: str) -> tuple[list[str], int]:
    """Keep lines (from the start or the end, per `keep`) until the token budget is used up.

    Returns the lines kept and how many were left out. keep="first" or "last".
    """
    ordered = list(lines) if keep == "first" else list(reversed(lines))
    kept: list[str] = []
    used = 0
    for line in ordered:
        cost = estimate_tokens(line) + 1
        if used + cost > budget_tokens:
            break
        kept.append(line)
        used += cost
    if keep == "last":
        kept.reverse()
    return kept, len(lines) - len(kept)


def compile_context(
    store: Store,
    viewer: str,
    since_tick: int,
    *,
    role_card: str,
    templates: Mapping[str, str] | None = None,
    notes: Sequence[str] = (),
    budget: int = 4000,
    max_hops: int = 3,
) -> str:
    """The text the viewer's model reads this turn, within about `budget` tokens.

    `since_tick` is the first tick that counts as new: changes and arrivals at or after it go in
    the "changes" and "inbox" sections.
    """
    templates = templates or {}
    sections: list[str] = [f"## Role\n{role_card}"]

    # ---- commitments ----
    commitments = _commitments(store, viewer)
    if commitments:
        sections.append("## Commitments\n" + "\n".join(commitments))

    # ---- changes since last turn (always shown, within a quarter of the budget) ----
    changes = store.changes_since(viewer, since_tick)
    tombstones = [_tombstone(c, store.belief(viewer, c.belief_id), templates) for c in changes]
    shown, hidden = _fit(tombstones, budget // 4, keep="first")
    if shown:
        extra = [f"(+{hidden} more changes not shown)"] if hidden else []
        sections.append("## Changed since last turn\n" + "\n".join(shown + extra))

    # ---- inbox (the newest arrivals, within a fifth of the budget) ----
    inbox = [
        f"- {o.id} tick {o.received_tick} {o.kind}"
        f"{' from ' + o.sender if o.sender else ''}: {_compact(o.payload)}"
        for o in store.observations(viewer, since_tick)
    ]
    shown, hidden = _fit(inbox, budget // 5, keep="last")
    if shown:
        older = [f"(+{hidden} older arrivals not shown)"] if hidden else []
        sections.append("## Inbox\n" + "\n".join(older + shown))

    # ---- working notes ----
    if notes:
        sections.append("## Notes to self\n" + "\n".join(f"- {n}" for n in notes))

    # ---- relevant beliefs: whatever room is left, nearest to what is happening first ----
    live = [b for b in store.beliefs(viewer) if b.status in _LIVE]
    seeds = {b.subject for b in live if b.updated_tick >= since_tick}
    seeds |= {a.target for a in store.actions(viewer) if a.target}
    seeds |= {b.subject for c in changes if (b := store.belief(viewer, c.belief_id))}
    distance = store.entity_distances(sorted(seeds), max_hops)
    far = max_hops + 1  # beliefs about entities nowhere near the seeds go last
    status_rank = {"suspect": 0, "active": 1}  # a suspect belief needs attention first
    live.sort(
        key=lambda b: (
            distance.get(b.subject, far),
            status_rank[b.status],
            -b.confidence,
            -b.updated_tick,
            b.id,
        )
    )

    used = sum(estimate_tokens(s) + 2 for s in sections)
    room = budget - used - 8  # a little room for the section heading
    lines: list[str] = []
    left_out = 0
    for belief in live:
        line = render_belief(belief, store.support_routes(viewer, belief.id), templates)
        cost = estimate_tokens(line) + 1
        if cost > room:
            left_out += 1
            continue
        lines.append(line)
        room -= cost
    if lines or left_out:
        tail = [f"(+{left_out} less relevant beliefs not shown)"] if left_out else []
        sections.append("## Beliefs\n" + "\n".join(lines + tail))
    return "\n\n".join(sections)
