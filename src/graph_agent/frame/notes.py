"""The baseline: the same team with one shared notes file instead of the graph.

To show what the graph is worth, a team runs twice on the same script: once with the graph, once
with this memory. Everything else is identical: the nodes, their goals, the tools (reading,
checking and outward), the model, the token budget and the checks. Only memory differs:

  graph   each node's context is compiled from its beliefs; claims carry their routes; a plan
          names what it rests on, so a correction flags exactly what rests on it, holds the
          actions built on it and reaches every copy; evidence exposes a lying sender and the
          team stops trusting it (see pack.py, runtime.py, nodes.py)
  notes   every item a node receives, every check result and every note a node writes is
          appended to one shared notes file, which every node reads (newest last, the oldest
          lines dropped when it no longer fits the budget). Nodes write notes instead of
          recording or sending beliefs. Nothing links a plan to what it rests on, so nothing is
          held or withdrawn and no sender is distrusted: the model has to notice by itself.

Fairness, as in the benchmark's "shared log" baseline: the notes are global (every node reads
everything, which the graph nodes cannot), the goals are the same words, and the pack's own
warnings (mails can lie, check what you can) are kept. What is not given is the graph's
machinery: that is what is being measured.

Turn it on with `notes_team(team)`: a copy of the team with settings.extra["memory"] = "notes",
the graph tools replaced by `note`, and the checker taken out. BasePack does the rest.
"""

from typing import TYPE_CHECKING

from ..core.compiler import estimate_tokens
from .spec import TeamSpec
from .tools import ToolSpec, schema_of

if TYPE_CHECKING:
    from .runtime import Item, Runtime

NOTES_PROMPT = (
    "\n\nThis team has no knowledge graph: its whole memory is one shared notes file, which every "
    "member reads. Wherever your instructions say to record something (assert_belief) or to send "
    "it to someone (send), write a note instead (note): one line saying what it is and what it "
    "rests on. Every member reads every note. Outward actions take no depends_on: leave it out."
)


def notes_team(team: TeamSpec) -> TeamSpec:
    """The same team on shared notes: agents keep their goals and tools, lose the graph tools and
    gain `note`; the checker (which needs beliefs and evidence) is left out."""
    copy = team.model_copy(deep=True)
    copy.name = f"{team.name} (shared notes, no graph)"
    copy.settings.extra["memory"] = "notes"
    dropped = {n.id for n in copy.nodes if n.type == "checker"}
    copy.nodes = [n for n in copy.nodes if n.id not in dropped]
    copy.links = [link for link in copy.links if not {link.src, link.dst} & dropped]
    for node in copy.nodes:
        if node.type in ("agent", "responder"):
            node.graph_tools = []
            node.tools = [*node.tools, "note"]
    return copy


def uses_notes(rt: "Runtime") -> bool:
    return rt.settings.extra.get("memory") == "notes"


class SharedNotes:
    """The notes file, and the `note` tool that writes to it. `writer` is the node whose turn it
    is (set when its context is compiled; turns run one at a time)."""

    def __init__(self, rt: "Runtime"):
        self.rt = rt
        self.lines: list[str] = []
        self.seen: set[str] = set()
        self.writer = ""

    def item(self, item: "Item", route: list[str]) -> None:
        """An item reached the team (once, however many nodes it was routed to)."""
        if item.id in self.seen:
            return
        self.seen.add(item.id)
        payload = item.payload
        if item.source.startswith("tool:"):
            text = f"{item.source.removeprefix('tool:')} says: " + "; ".join(
                f"{s} {p} = {v}" for s, p, v in item.claims
            )
        else:
            sender = " via ".join(route)
            subject = payload.get("subject", "")
            text = f"from {sender}: {subject}: {payload.get('body') or payload.get('text') or ''}"
        self.lines.append(f"[tick {item.tick}] {text}")

    def write(self, text: str) -> str:
        writer = self.writer or "someone"
        self.lines.append(f"[tick {self.rt.tick}] {writer}: {text.strip()}")
        for node_id, node in self.rt.nodes.items():
            if node_id != writer and node.spec.type in ("agent", "responder"):
                self.rt.wake(node_id, "message")
        return "noted"

    def render(self, budget: int) -> str:
        """The newest lines that fit in `budget` tokens, oldest first."""
        kept: list[str] = []
        used = 0
        for line in reversed(self.lines):
            used += estimate_tokens(line)
            if used > budget:
                kept.append(f"(... {len(self.lines) - len(kept)} older notes no longer fit)")
                break
            kept.append(line)
        return "## Shared notes\n" + "\n".join(reversed(kept))

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                "note",
                "Write one line to the team's shared notes, which every member reads.",
                schema_of({"text": {"type": "string"}}, ["text"]),
                lambda a: self.write(str(a["text"])),
            )
        ]
