"""Spaces: live runs the console can watch and drive.

A space is one team running on the frame: its runtime, its store, its world (whatever the pack
simulates), and a lock, since the HTTP server reads it from other threads while it runs. A space
is created from a team file (what the canvas drew) and options: which model, the store, whether
outward actions wait for a person.

Models: "stand-in" (the pack's scripted team: free, deterministic) or a real model name (needs
ANTHROPIC_API_KEY; every request is cached on disk, so a run already made replays for free).
"""

import os
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graph_agent.core.model import Belief, Observation
from graph_agent.frame.console import ConsolePack, Session

from ..core.store import Store
from ..frame.events import EventLog
from ..frame.nodes import approvals
from ..frame.runtime import Runtime
from ..frame.spec import TeamSpec
from ..harness.llm import AnthropicClient, CachedClient, ModelClient
from ..stores.falkor import FalkorStore
from ..stores.memory import MemoryStore

ROOT = Path(__file__).resolve().parents[3]  # the repository: .env and runs/ live here


def _env() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() and value.strip() and not line.startswith("#"):
                os.environ.setdefault(key.strip(), value.strip())


def make_client(model: str, pack: ConsolePack, team: TeamSpec, cache: Path) -> ModelClient:
    """The model a space runs on. `cache`: the folder of model caches (each person's own, hosted:
    what one person's run asked, with their mail in it, is never replayed to another)."""
    if model == "stand-in":
        return pack.stand_in(team)
    _env()
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("a real model needs ANTHROPIC_API_KEY (in .env)")
    real = AnthropicClient(
        model, key, max_tokens=2000, workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    )
    return CachedClient(real, cache / f"{model}-mt2000{pack.cache_suffix}")


@dataclass
class Space:
    id: str
    pack: str
    name: str
    model: str
    session: Session
    store: Store
    owner: str = "local"  # who started it (users.User.id): only they can see or drive it
    created: float = field(default_factory=time.time)
    lock: threading.RLock = field(default_factory=threading.RLock)
    running: bool = False
    error: str = ""
    _thread: threading.Thread | None = None

    @property
    def runtime(self) -> Runtime:
        return self.session.runtime

    # ---- driving it -----------------------------------------------------------------------------

    @property
    def limit(self) -> int:
        ticks = self.runtime.settings.ticks
        return ticks if ticks is not None else 100

    @property
    def finished(self) -> bool:
        rt = self.runtime
        return rt.stopped or rt.finished() or rt.tick >= self.limit

    def step(self) -> None:
        with self.lock:
            if not self.finished:
                self.runtime.step()

    def play(self, delay: float = 0.0) -> None:
        """Run tick after tick in the background until it is done or paused."""
        if self.running:
            return
        self.running = True

        def loop() -> None:
            try:
                while self.running and not self.finished:
                    self.step()
                    if delay:
                        time.sleep(delay)
            except Exception as error:  # shown in the console, not lost in a thread
                self.error = f"{type(error).__name__}: {error}"
            finally:
                self.running = False
                if self.finished:
                    self.finish()

        self._thread = threading.Thread(target=loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        self.running = False

    def finish(self) -> None:
        with self.lock:
            if not any(e.kind == "run_end" for e in self.runtime.log.events[-3:]):
                self.runtime.log.emit(self.runtime.tick, "run_end", score=self.score())

    def decide(self, proposal_id: str, approved: bool) -> str:
        with self.lock:
            return approvals(self.runtime).decide(proposal_id, approved, by="person")

    # ---- reading it ---------------------------------------------------------------------------

    def score(self) -> dict[str, Any]:
        return self.session.score()

    def clock(self, tick: int) -> str:
        return self.session.clock(tick)

    def summary(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pack": self.pack,
            "name": self.name,
            "title": self.runtime.team.name,
            "model": self.model,
            "tick": self.runtime.tick,
            "clock": self.clock(self.runtime.tick),
            "running": self.running,
            "finished": self.finished,
            "error": self.error,
            "events": len(self.runtime.log.events),
            "store": type(self.store).__name__,
            "created": self.created,
        }

    def state(self) -> dict[str, Any]:
        return self._read(self._state)

    def _read[T](self, read: Callable[[], T]) -> T:
        """Run a read for the page. A day being played holds the lock for as long as the agents'
        model calls take (a minute or more), and the page must not wait that long: the read waits
        a moment for the lock, then goes ahead without it. The graph stores are safe to read while
        a day writes to them; a read that collides with a write in progress is tried again."""
        got = self.lock.acquire(timeout=0.25)
        try:
            for attempt in range(5):
                try:
                    return read()
                except RuntimeError:  # e.g. a dict changed size while it was being read
                    if got or attempt == 4:
                        raise
                    time.sleep(0.05)
            raise AssertionError("unreachable")
        finally:
            if got:
                self.lock.release()

    def _state(self) -> dict[str, Any]:
        rt = self.runtime
        history: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for event in rt.log.events:
            if event.kind == "change":
                key = (str(event.data["viewer"]), str(event.data["belief"]))
                history.setdefault(key, []).append(
                    {
                        "tick": event.tick,
                        "status": event.data["new"],
                        "reason": event.data["reason"],
                    }
                )
        nodes: list[dict[str, Any]] = []
        beliefs: dict[str, list[dict[str, Any]]] = {}
        for node in rt.nodes.values():
            nodes.append(
                {
                    "id": node.id,
                    "type": node.spec.type,
                    "kind": node.kind,
                    "label": node.spec.label or node.id,
                    "role": node.spec.role,
                    "pending": sorted(rt.pending.get(node.id, set())),
                    "distrusts": sorted(rt.distrusted(node.id)),
                    "last_turn": getattr(node, "last_turn", None),
                }
            )
            if node.kind in ("model", "scripted"):
                beliefs[node.id] = [
                    self._belief(node.id, b, history.get((node.id, b.id), []))
                    for b in rt.store.beliefs(node.id)
                ]
        outside = sorted(
            {agent for _, agent in rt.exposed_pairs if agent not in rt.nodes}
            | {
                str(e.data["source"])
                for e in rt.log.events
                if e.kind == "item" and str(e.data.get("source", "")) not in rt.nodes
            }
        )
        links = [{"src": a, "dst": b} for a in rt.nodes for b in rt.network.neighbours(a) if a < b]
        book = approvals(rt)
        return {
            **self.summary(),
            "team": rt.team.model_dump(mode="json"),
            "nodes": nodes,
            "outside": [
                {
                    "id": source,
                    "quarantined_by": sorted(v for v, a in rt.exposed_pairs if a == source),
                }
                for source in outside
                if not source.startswith("tool:")
            ],
            "links": links,
            "beliefs": beliefs,
            "proposals": [
                {
                    "id": p.id,
                    "node": p.node,
                    "tool": p.tool,
                    "arguments": p.arguments,
                    "basis": p.basis,
                    "tick": p.tick,
                    "status": p.status,
                    "result": p.result,
                    "note": p.note,
                }
                for p in book.proposals.values()
            ],
            "exposures": [
                {
                    "viewer": e.viewer,
                    "agent": e.agent,
                    "tick": e.day,
                    "reason": e.reason,
                    "changed": [c.belief_id for c in e.changes],
                }
                for e in rt.exposures
            ],
            "world": self.session.world(),
            "clocks": [self.session.clock(t) for t in range(max(self.runtime.tick, self.limit))],
            "score": self.score(),
        }

    def _belief(self, viewer: str, b: Belief, history: list[dict[str, Any]]) -> dict[str, Any]:
        rt = self.runtime
        return {
            "id": b.id,
            "subject": b.subject,
            "predicate": b.predicate,
            "value": b.value,
            "text": rt.pack.templates.get(b.predicate, "{subject} {predicate} = {value}").format(
                subject=b.subject, value=b.value, predicate=b.predicate
            ),
            "origin": b.origin,
            "status": b.status,
            "born": b.created_tick,
            "routes": [list(r) for r in rt.store.support_routes(viewer, b.id)],
            "sources": rt.store.sources(viewer, b.id),
            "history": history,
        }

    # ---- why ------------------------------------------------------------------------------------

    def why(self, viewer: str, belief_id: str) -> dict[str, Any]:
        return self._read(lambda: self._why(viewer, belief_id))

    def _why(self, viewer: str, belief_id: str) -> dict[str, Any]:
        rt, store = self.runtime, self.store
        belief = store.belief(viewer, belief_id)
        if belief is None:
            raise KeyError(f"{viewer} has no belief {belief_id}")
        recorded = set(rt.supports.get((viewer, belief_id), []))
        observations = [
            o
            for o in store.observations(viewer, 0)
            if (o.id in recorded if recorded else belief_id in _supported(store, viewer, o, belief))
        ]
        upstream = [
            {
                "observation": o.id,
                "kind": o.kind,
                "sender": o.sender,
                "tick": o.received_tick,
                "route": o.payload.get("route"),
                "item": o.payload.get("item"),
                "subject": o.payload.get("subject"),
                "source_belief": o.payload.get("source_belief"),
            }
            for o in observations
        ]
        downstream = [
            {"node": receiver, "belief": copy, "status": _status(store, receiver, copy)}
            for receiver, copy in rt.copies.get((viewer, belief_id), [])
        ]
        derived_from = [
            {"belief": s, "status": _status(store, viewer, s), "text": _text(rt, viewer, s)}
            for s in store.sources(viewer, belief_id)
        ]
        by_action = {p.action_id: p for p in approvals(rt).proposals.values()}
        dependents: list[dict[str, Any]] = []
        for d, h in sorted(store.dependents(viewer, belief_id).items(), key=lambda x: x[1]):
            proposal = by_action.get(d)
            if proposal is not None:
                args = ", ".join(str(v) for v in proposal.arguments.values())
                status, text = proposal.status, f"{proposal.tool}({args})"
            else:
                status, text = _status(store, viewer, d), _text(rt, viewer, d)
            dependents.append({"id": d, "hops": h, "status": status, "text": text})
        cut = sorted(
            {a for r in store.support_routes(viewer, belief_id) for a in r} & rt.distrusted(viewer)
        )
        changes = [
            {"tick": e.tick, "status": e.data["new"], "reason": e.data["reason"]}
            for e in rt.log.events
            if e.kind == "change" and e.data["viewer"] == viewer and e.data["belief"] == belief_id
        ]
        resting = [
            {"id": p.id, "tool": p.tool, "status": p.status, "arguments": p.arguments}
            for p in approvals(rt).proposals.values()
            if p.node == viewer and belief_id in p.basis
        ]
        cypher = {
            "routes": (
                "MATCH (o:Observation)-[:SUPPORTS]->(b:Belief {id: $id}) "
                "OPTIONAL MATCH (o)-[r:RELAYED_VIA]->(a:Agent) "
                "RETURN o.id, o.kind, r.hop, a.id ORDER BY o.id, r.hop"
            ),
            "dependents": (
                "MATCH (d)-[:DERIVED_FROM*1..8]->(b:Belief {id: $id}) "
                "RETURN DISTINCT labels(d)[1], d.id, d.status"
            ),
            "history": (
                "MATCH (c:Correction)-[r:INVALIDATED]->(b:Belief {id: $id}) "
                "RETURN r.tick, r.new_status, c.type, c.target, c.reason ORDER BY r.tick"
            ),
        }
        live: dict[str, Any] = {}
        if isinstance(store, FalkorStore):
            for name, query in cypher.items():
                started = time.perf_counter()
                rows = store.query(query, id=belief_id)
                live[name] = {
                    "rows": [[str(c) for c in row] for row in rows],
                    "ms": round((time.perf_counter() - started) * 1000, 2),
                }
        return {
            "viewer": viewer,
            "belief": self._belief(viewer, belief, []),
            "upstream": upstream,
            "downstream": downstream,
            "derived_from": derived_from,
            "dependents": dependents,
            "cut_by_distrust": cut,
            "changes": changes,
            "actions": resting,
            "cypher": cypher,
            "live": live,
            "store": type(store).__name__,
        }


def _supported(store: Store, viewer: str, o: Observation, belief: Belief) -> set[str]:
    """Which of the viewer's beliefs this observation supports (by the routes it would add)."""
    route = tuple(str(a) for a in (o.payload.get("route") or ([o.sender] if o.sender else [])))
    routes = store.support_routes(viewer, belief.id)
    same_subject = o.payload.get("subject") in (None, belief.subject)
    item_about = o.payload.get("item") is not None
    return (
        {belief.id}
        if (route in routes or (not route and () in routes)) and (same_subject or item_about)
        else set()
    )


def _status(store: Store, viewer: str, belief_id: str) -> str:
    b = store.belief(viewer, belief_id)
    return b.status if b is not None else "?"


def _text(rt: Runtime, viewer: str, belief_id: str) -> str:
    b = rt.store.belief(viewer, belief_id)
    if b is None:
        node = rt.store.get(viewer, belief_id)
        return node.type if node is not None and hasattr(node, "type") else belief_id  # type: ignore[union-attr]
    template = rt.pack.templates.get(b.predicate, "{subject} {predicate} = {value}")
    return template.format(subject=b.subject, value=b.value, predicate=b.predicate)


# ---- the registry -------------------------------------------------------------------------------


class Spaces:
    def __init__(self) -> None:
        self.spaces: dict[str, Space] = {}

    def get(self, space_id: str) -> Space:
        space = self.spaces.get(space_id)
        if space is None:
            raise KeyError(f"no space {space_id}")
        return space

    def create(
        self,
        pack: ConsolePack,
        team: TeamSpec,
        *,
        name: str = "",
        model: str = "stand-in",
        store: str = "memory",
        options: dict[str, str] | None = None,
        owner: str = "local",
        cache: Path = ROOT / "runs" / "cache",
    ) -> Space:
        space_id = uuid.uuid4().hex[:8]
        the_store: Store = (
            FalkorStore(graph_name=f"space_{space_id}", keep=True)
            if store == "falkor"
            else MemoryStore()
        )
        client = make_client(model, pack, team, cache)
        session = pack.start(team, client, the_store, EventLog(), options or {})
        space = Space(space_id, pack.name, name or team.name, model, session, the_store, owner)
        with space.lock:
            session.runtime.start()
        self.spaces[space_id] = space
        return space

    def delete(self, space_id: str) -> None:
        space = self.spaces.pop(space_id)
        space.pause()
        space.runtime.close()
