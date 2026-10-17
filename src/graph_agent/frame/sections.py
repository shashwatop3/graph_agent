"""Context sections any pack can add to what a node reads (see BasePack.sections).

    team(rt, node)                      who the node can send beliefs to, with their roles
    unsent_plans(rt, node, plans, ...)  plans the node made that no teammate has received
    actions(rt, node)                   the node's outward actions, with the held ones explained

Each returns [(heading, lines)]; an empty list of lines leaves the section out.
"""

from collections.abc import Callable, Container

from ..core.model import Belief
from .nodes import approvals
from .runtime import Runtime
from .spec import NodeSpec

Lines = list[tuple[str, list[str]]]


def team(rt: Runtime, node: NodeSpec) -> Lines:
    lines: list[str] = []
    for peer in rt.network.neighbours(node.id):
        spec = rt.team.node(peer) if peer in rt.nodes else None
        if spec is not None:
            lines.append(f"- {peer}: {spec.role or spec.type}")
    return [("Your team (you can send them beliefs)", lines)]


def unsent_plans(
    rt: Runtime, node: NodeSpec, plans: Container[str], render: Callable[[Belief], str]
) -> Lines:
    """Plans (beliefs whose predicate is in `plans`) this node made that no teammate has: a plan
    nobody hears of is never carried out."""
    peers = rt.network.neighbours(node.id)
    if not peers:
        return []
    doers = [p for p in peers if rt.team.node(p).type == "responder"] or peers
    lines: list[str] = []
    for b in rt.store.beliefs(node.id):
        if b.origin != "derived" or b.predicate not in plans or b.status != "active":
            continue
        if rt.copies.get((node.id, b.id)):
            continue  # someone has it
        lines.append(
            f'- {b.id} {render(b)}: nobody has it yet; send(to="{doers[0]}", belief_id="{b.id}")'
        )
    return [("Plans you have not sent yet", lines)]


def actions(rt: Runtime, node: NodeSpec) -> Lines:
    lines: list[str] = []
    for p in approvals(rt).proposals.values():
        if p.node != node.id:
            continue
        # sorted: the model cache stores arguments sorted, so a replay renders them the same
        args = ", ".join(f"{k}={v}" for k, v in sorted(p.arguments.items()))
        basis = ", ".join(p.basis) or "nothing"
        line = f"- {p.id} {p.tool}({args}) resting on {basis}: {p.status}"
        if p.result:
            line += f" -> {p.result}"
        if p.status == "held":
            line += f". HELD: {p.note}"
        lines.append(line)
    return [("Your actions (held ones need you: undo or adjust them)", lines[-12:])]
