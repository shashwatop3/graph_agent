"""The comparison systems: how well do agents do WITHOUT the knowledge graph?

Each baseline plugs into the same game loop as the graph setup. The simulator, imposters, evidence,
model, token budget and tool names for acting are identical. Only memory differs:

  B0  isolated       no communication. An agent sees only the published evidence and must act on
                     its own. (Shows what coordination is worth at all.)
  B1  shared log     everything said or published goes into one log everyone reads, newest last,
                     trimmed to the budget. Nothing marks a claim as refuted: the agent has to
                     notice that evidence contradicts a message by itself.
  B2  vector memory  the same stream goes into a similarity-searchable memory. Each turn the agent
                     reads the lines most similar to its own situation, plus the latest few.
  B3  prompt-only    B1's log, with a strong instruction to cross-check messages against the
                     evidence and to pass corrections on. (Is a good prompt enough?)

B1, B2 and B3 also come in an "own" variant (B1o, B2o, B3o). The default ("global") reads every
message anyone sent in the whole game, which the graph agents cannot: a shared log ignores who is
allowed to talk to whom. That makes it a deliberately generous baseline. The "own" variant shows an
agent only the messages it sent or received, so it has exactly the information a graph agent has
and differs only in how memory is organised. Compare the graph against both.

Fairness choices, so that each is a strong version and not a straw man
  * All baselines are told the same map the graph agents can query (the field order and the days
    each step takes), and the same role card. Nothing is withheld that the graph agents know.
  * Messages carry the same structured claim and the engine records the same route; the route is
    shown on every log line.
  * B2 uses TF-IDF similarity (pure Python, free, deterministic). A learned embedding model could
    only help it, so this is a floor for B2; swap one in when a provider is available.
  * The graph setups' evidence rule (blame the sender, drop support) is NOT given to baselines:
    that rule is part of what is being tested.
"""

import math
import re
from collections import Counter
from collections.abc import Collection
from functools import partial

from ..adapters import ringfire
from ..core.compiler import estimate_tokens
from ..core.model import Action
from ..sim.comms import Message
from ..sim.game import DayResult, Game
from .pipeline import Exposure
from .types import ExecuteFn, SendFn

CHECKLIST = (
    "Before you act on any claim, check it against the PUBLISHED evidence. A claim whose day "
    "does not match what was published is false; do not pass it on and do not water because of "
    "it. When you learn that something you told others was false, tell them, and recompute any "
    "forecast you built on it. Prefer information that reached you by a short route from a source "
    "you trust, and stop trusting agents whose claims keep turning out false."
)


def _route(message: Message) -> str:
    return ">".join(f"A{agent}" for agent in message.route)


def _message_line(message: Message) -> str:
    claim = message.claim
    return (
        f"day {message.day}: A{message.sender} told A{message.receiver} "
        f"that fire reaches F{claim.field_id} on day {claim.day} (route {_route(message)})"
    )


def _fit_last(lines: list[str], budget_tokens: int) -> tuple[list[str], int]:
    """The newest lines that fit. Returns them (oldest first) and how many were left out."""
    kept: list[str] = []
    used = 0
    for line in reversed(lines):
        cost = estimate_tokens(line) + 1
        if used + cost > budget_tokens:
            break
        kept.append(line)
        used += cost
    kept.reverse()
    return kept, len(lines) - len(kept)


class BaselineTools:
    """The tools a baseline agent has: tell a neighbour something, and act. No memory tools."""

    def __init__(
        self,
        agent: int,
        send: SendFn,
        execute: ExecuteFn,
        names: tuple[str, ...] = ("send", "act"),
    ):
        self.agent = agent
        self._send = send
        self._execute = execute
        self.names = names
        self.now = 0
        self._actions = 0

    def send(self, to: str, field: str, day: int) -> str:
        """Tell another agent that fire reaches a field on a day (to A4, field F3, day 5)."""
        try:
            receiver, field_number = int(to[1:]), int(field[1:])
        except (ValueError, IndexError):
            return "error: name agents like A4 and fields like F3"
        try:
            # a claim you were told is passed on along its route; anything else you report yourself
            return self._send(self.agent, receiver, field_number, int(day), True)
        except ValueError as error:
            return f"error: {error}"

    def act(self, type: str, target: str | None = None) -> str:
        """Commit to an action: 'water' (your own fields, today) or 'link' (target: an agent)."""
        self._actions += 1
        action = Action(
            id=f"X{self.agent}_{self._actions}",
            owner=f"A{self.agent}",
            type=type,
            target=target,
            status="committed",
        )
        try:
            return f"{action.id}: {self._execute(action)}"
        except ValueError as error:
            return f"error: {error}"


class _LogBackend:
    """Shared behaviour of the baselines: they keep a stream of lines and show some of it."""

    name = "baseline"
    tool_names = ("send", "act")
    strong_prompt = False

    def __init__(self, scope: str = "global"):
        if scope not in ("global", "own"):
            raise ValueError("scope must be 'global' or 'own'")
        self.scope = scope
        if scope == "own":
            self.name += "-own"
        self.exposures: list[Exposure] = []  # baselines never distrust anyone on the agent's behalf
        self.lines: list[str] = []
        self.audience: list[set[int] | None] = []  # per line: who may read it (None = everyone)
        self._evidence_line: dict[int, int] = {}  # field -> index of its "PUBLISHED" line
        self.map_lines: list[str] = []
        self.n_agents = 0
        self.fields: dict[int, tuple[int, ...]] = {}
        self.water: int | None = None  # waterings per agent, from the game's rules

    # ---- feeding it the game ------------------------------------------------------------------

    def start(self, game: Game) -> None:
        world = game.sim.world
        self.n_agents = world.config.n_agents
        self.fields = {n: tuple(world.fields_of(n)) for n in range(self.n_agents)}
        self.water = game.sim.rules.water_per_agent
        for edge in world.edges:
            if not edge.hidden:
                owner = world.owner(edge.src)
                self.map_lines.append(
                    f"F{edge.src} -> F{edge.dst}: fire takes {edge.weight} day(s) "
                    f"(A{owner} owns F{edge.src})"
                )
        self.game = game
        for field_number, _ in world.initial_fires:
            self._publish(0, field_number, game.audience(field_number, 0))

    def _publish(self, day: int, field_number: int, audience: Collection[int]) -> None:
        self._evidence_line[field_number] = len(self.lines)
        self.lines.append(f"day {day}: PUBLISHED: field F{field_number} caught fire on day {day}")
        self.audience.append(set(audience))

    def message(self, message: Message) -> None:
        self.lines.append(_message_line(message))
        # in the global log everyone reads every message; in the own-inbox log only its two ends do
        self.audience.append(None if self.scope == "global" else {message.sender, message.receiver})
        # told about a field that has already burnt: the engine shows them the truth at once
        line = self._evidence_line.get(message.claim.field_id)
        readers = self.audience[line] if line is not None else None
        if readers is not None:
            readers.add(message.receiver)

    def day(self, game: Game, result: DayResult) -> None:
        for edge in result.report.revealed_hidden:
            self.map_lines.append(
                f"F{edge.src} -> F{edge.dst}: a hidden path, now revealed; "
                f"takes {edge.weight} day(s)"
            )
        start = (
            {f for f, _ in game.sim.world.initial_fires} if result.report.day == 0 else set[int]()
        )
        for evidence in result.evidence:
            if evidence.field_id not in start:  # start fires were published before day 0
                self._publish(evidence.day, evidence.field_id, evidence.audience)

    # ---- what the agent reads -----------------------------------------------------------------

    def role(self, number: int) -> str:
        card = ringfire.role_card(
            ringfire.agent_id(number), self.n_agents, self.fields.get(number, ())
        )
        return f"## Role\n{card}" + (f"\n\n## Checklist\n{CHECKLIST}" if self.strong_prompt else "")

    def map_section(self) -> str:
        return "## Map\n" + "\n".join(self.map_lines)

    def readable(self, number: int) -> list[int]:
        """Indexes of the lines this agent may read: messages, and evidence it is entitled to."""
        return [i for i, who in enumerate(self.audience) if who is None or number in who]

    def visible_lines(self, number: int, budget_tokens: int) -> tuple[list[str], int]:
        """The lines to show and how many older ones had to be left out."""
        raise NotImplementedError

    def context(self, number: int, day: int, budget: int) -> str:
        head = f"{self.role(number)}\n\n{self.map_section()}"
        room = budget - estimate_tokens(head) - 12
        lines, left_out = self.visible_lines(number, max(room, 0))
        title = self.section_title
        older = [f"(+{left_out} older lines not shown)"] if left_out else []
        return f"{head}\n\n## {title}\n" + "\n".join(older + lines)

    section_title = "Log"

    def toolbox(self, number: int, send: SendFn, execute: ExecuteFn) -> BaselineTools:
        return BaselineTools(number, send, execute, self.tool_names)


class IsolatedBackend(_LogBackend):
    """B0: no communication. Only published evidence is visible, and agents cannot send."""

    name = "B0-isolated"
    tool_names = ("act",)
    section_title = "Published evidence"

    def visible_lines(self, number: int, budget_tokens: int) -> tuple[list[str], int]:
        mine = [self.lines[i] for i in self.readable(number) if "PUBLISHED" in self.lines[i]]
        return _fit_last(mine, budget_tokens)


class SharedLogBackend(_LogBackend):
    """B1: one log of everything, newest last, trimmed to the budget."""

    name = "B1-shared-log"
    section_title = "Shared log (everything said and published, oldest first)"

    def visible_lines(self, number: int, budget_tokens: int) -> tuple[list[str], int]:
        return _fit_last([self.lines[i] for i in self.readable(number)], budget_tokens)


class PromptOnlyBackend(SharedLogBackend):
    """B3: B1, plus a strong prompt to cross-check messages and pass corrections on."""

    name = "B3-prompt-only"
    strong_prompt = True


# ---- B2: a similarity-searchable memory ---------------------------------------------------------


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def most_similar(documents: list[str], query: str, k: int) -> list[int]:
    """Indexes of the `k` documents closest to `query` by TF-IDF cosine, best first.

    Ties go to the more recent document. Pure Python, deterministic, no model needed.
    """
    if not documents:
        return []
    doc_words = [Counter(_words(d)) for d in documents]
    frequency = Counter(word for counts in doc_words for word in counts)
    n = len(documents)

    def vector(counts: Counter[str]) -> dict[str, float]:
        return {
            w: c * (math.log((n + 1) / (frequency.get(w, 0) + 1)) + 1) for w, c in counts.items()
        }

    q = vector(Counter(_words(query)))
    q_norm = math.sqrt(sum(v * v for v in q.values())) or 1.0
    scored: list[tuple[float, int]] = []
    for index, counts in enumerate(doc_words):
        d = vector(counts)
        norm = math.sqrt(sum(v * v for v in d.values())) or 1.0
        dot = sum(q[w] * d[w] for w in q if w in d)
        scored.append((dot / (q_norm * norm), index))
    scored.sort(key=lambda s: (-s[0], -s[1]))
    return [index for _, index in scored[:k]]


class VectorMemoryBackend(_LogBackend):
    """B2: each turn the agent reads the lines most relevant to it, plus the newest ones."""

    name = "B2-vector-memory"
    section_title = "Memory (the lines most relevant to you, then the latest)"
    recent = 4  # always show this many of the newest lines

    def visible_lines(self, number: int, budget_tokens: int) -> tuple[list[str], int]:
        mine = self.readable(number)
        docs = [self.lines[i] for i in mine]
        # the agent's situation as a query: its own field and its neighbours' fields
        around = [(number + d) % self.n_agents for d in (-1, 0, 1)]
        query = f"A{number} " + " ".join(f"A{a} F{a}" for a in around) + " fire reaches field day"
        newest = list(range(max(0, len(docs) - self.recent), len(docs)))
        ranked = [i for i in most_similar(docs, query, 40) if i not in newest]
        chosen: list[int] = []
        used = 0
        for index in newest + ranked:  # the newest first, then by similarity, until the budget
            cost = estimate_tokens(docs[index]) + 1
            if used + cost > budget_tokens:
                continue
            chosen.append(index)
            used += cost
        chosen.sort()  # show in time order
        return [docs[i] for i in chosen], len(docs) - len(chosen)


BASELINES = {
    "B0": IsolatedBackend,
    "B1": SharedLogBackend,
    "B2": VectorMemoryBackend,
    "B3": PromptOnlyBackend,
    "B1o": partial(SharedLogBackend, scope="own"),
    "B2o": partial(VectorMemoryBackend, scope="own"),
    "B3o": partial(PromptOnlyBackend, scope="own"),
}
