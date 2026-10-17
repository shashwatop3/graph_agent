"""The HTTP API the console uses, plus the console itself.

    uv run python -m graph_agent.service            # http://127.0.0.1:8765

    GET  /api/packs                      the packs the page can load, and their run options
    GET  /api/catalogue?pack=life        node types, tools, predicates, triggers and link kinds
    GET  /api/templates                  ready-made teams; GET /api/templates/{pack}/{name};
                                         POST the same path with settings for a variant
    POST /api/validate                   check a team file
    GET  /api/spaces                     live runs;  POST /api/spaces  {pack, team, model, ...}
    GET  /api/spaces/{id}                everything the console shows (nodes, beliefs, actions,
                                         exposures, the world, the score)
    POST /api/spaces/{id}/step | play | pause
    GET  /api/spaces/{id}/events?since=N the event log;  GET .../stream  the same, live (SSE)
    GET  /api/spaces/{id}/why/{node}/{belief}   why a node believes something (with the Cypher;
                                         run live, with timings, when the store is FalkorDB)
    POST /api/spaces/{id}/approvals/{proposal}  {approved: true|false}
    GET  /api/runs                       recorded runs to replay from the model cache
    /api/connections, /api/packs/{pack}/setup   your apps and your agents (service/connections.py)

Local only by default: it binds 127.0.0.1, and a real model run spends from the key in .env.
Hosted (GRAPH_AGENT_PUBLIC_URL set): people sign in with Google first (auth.py, users.py).
"""

import asyncio
import json
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from ..frame.nodes import catalogue_info
from ..frame.spec import TeamSpec
from .auth import current_user, guard
from .auth import router as auth_router
from .connections import router as connections_router
from .registry import pack_named, packs_for
from .spaces import ROOT, Spaces
from .users import User, hosted, secret_key, secrets_of

CONSOLE = ROOT / "viewer" / "console" / "dist"

TRIGGERS = {
    "tick": "every tick of the clock",
    "schedule": "every N ticks (every, at)",
    "item": "an item reached it (it owns what the item is about)",
    "message": "a teammate sent it a belief",
    "change": "one of its beliefs changed (a correction reached it)",
    "due": "a belief of its own falls due soon (within)",
    "exposure": "a teammate was exposed as unreliable",
    "approval": "a person approved or rejected its action",
}
LINKS = {
    "feeds": "a stream hands its items to a router or node",
    "owns": "a node looks after an entity, or every entity of a type (type:Flight)",
    "talks_to": "two nodes can send each other beliefs",
    "watches": "a responder or checker reacts to this node's cascades",
}


class CreateSpace(BaseModel):
    pack: str
    team: dict[str, Any]
    name: str = ""
    model: str = "stand-in"
    store: str = "memory"
    options: dict[str, str] = {}


class Decision(BaseModel):
    approved: bool


def create_app(spaces: Spaces | None = None) -> FastAPI:
    if hosted():
        secret_key()  # refuse to start without it, rather than fail at the first sign-in
    app = FastAPI(title="graph-agent console", version="0.1.0", dependencies=[Depends(guard)])
    registry = spaces or Spaces()
    app.state.spaces = registry

    def space_or_404(space_id: str, user: User):  # noqa: ANN202
        try:
            space = registry.get(space_id)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        if space.owner != user.id:  # someone else's run: as if there were none
            raise HTTPException(404, f"no space {space_id}")
        return space

    You = Depends(current_user)  # the person asking (the local one, when not hosted)

    def own_key(user: User) -> str | None:
        """Hosted: the person's own Anthropic key ("" if they have none). Local: None (.env)."""
        return secrets_of(user).get("ANTHROPIC_API_KEY", "") if hosted() else None

    # ---- building a team ----------------------------------------------------------------------

    def pack_or_404(name: str, user: User):  # noqa: ANN202
        try:
            return pack_named(name, user)
        except ValueError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/packs")
    def packs(user: User = You) -> list[dict[str, Any]]:
        return [
            {
                "name": pack.name,
                "title": pack.title,
                "options": [
                    {
                        "key": o.key,
                        "label": o.label,
                        "choices": [{"value": c.value, "label": c.label} for c in o.choices],
                    }
                    for o in pack.options
                ],
            }
            for pack in packs_for(user).values()
        ]

    @app.get("/api/catalogue")
    def catalogue(pack: str = "life", user: User = You) -> dict[str, Any]:
        extra = pack_or_404(pack, user).catalogue()
        return {
            "nodes": [*catalogue_info(), *extra.nodes],
            "tools": extra.tools,
            "graph_tools": [
                "recall",
                "explain",
                "traverse",
                "shortest_path",
                "assert_belief",
                "retract",
                "send",
                "act",
            ],
            "predicates": extra.predicates,
            "triggers": TRIGGERS,
            "links": LINKS,
        }

    @app.get("/api/templates")
    def templates(user: User = You) -> list[dict[str, str]]:
        return [
            {"pack": pack.name, "name": t.name, "title": t.title, "description": t.description}
            for pack in packs_for(user).values()
            for t in pack.templates()
        ]

    @app.get("/api/templates/{pack}/{name}")
    def template(pack: str, name: str, user: User = You) -> dict[str, Any]:
        return build_template(pack, name, {}, user)

    @app.post("/api/templates/{pack}/{name}")
    def template_variant(
        pack: str, name: str, options: dict[str, Any], user: User = You
    ) -> dict[str, Any]:
        """A ready-made team with the pack's own settings (for example how many agents)."""
        return build_template(pack, name, options, user)

    def build_template(
        pack: str, name: str, options: dict[str, Any], user: User
    ) -> dict[str, Any]:
        chosen = pack_or_404(pack, user)
        if name not in {t.name for t in chosen.templates()}:
            raise HTTPException(404, f"no template {pack}/{name}")
        return chosen.team(name, options).model_dump(mode="json")

    @app.post("/api/validate")
    def validate(team: dict[str, Any]) -> dict[str, Any]:
        try:
            TeamSpec.model_validate(team)
        except ValidationError as error:
            return {"ok": False, "errors": [e["msg"] for e in error.errors()]}
        return {"ok": True, "errors": []}

    # ---- spaces ---------------------------------------------------------------------------------

    @app.get("/api/spaces")
    def list_spaces(user: User = You) -> list[dict[str, Any]]:
        return [s.summary() for s in registry.spaces.values() if s.owner == user.id]

    @app.post("/api/spaces")
    def create_space(body: CreateSpace, user: User = You) -> dict[str, Any]:
        try:
            team = TeamSpec.model_validate(body.team)
            space = registry.create(
                pack_or_404(body.pack, user),
                team,
                name=body.name,
                model=body.model,
                store=body.store,
                options=body.options,
                owner=user.id,
                cache=user.folder / "runs" / "cache",  # local: the repository's runs/cache
                key=own_key(user),
            )
        except (ValidationError, ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from error
        return space.summary()

    @app.delete("/api/spaces/{space_id}")
    def delete_space(space_id: str, user: User = You) -> dict[str, str]:
        space_or_404(space_id, user)
        registry.delete(space_id)
        return {"deleted": space_id}

    @app.get("/api/spaces/{space_id}")
    def state(space_id: str, user: User = You) -> dict[str, Any]:
        return space_or_404(space_id, user).state()

    @app.post("/api/spaces/{space_id}/step")
    def step(space_id: str, user: User = You) -> dict[str, Any]:
        space = space_or_404(space_id, user)
        if space.running:
            raise HTTPException(409, "it is playing; pause it first")
        space.step()
        if space.finished:
            space.finish()
        return space.summary()

    @app.post("/api/spaces/{space_id}/play")
    def play(space_id: str, delay: float = 0.0, user: User = You) -> dict[str, Any]:
        space = space_or_404(space_id, user)
        space.play(delay)
        return space.summary()

    @app.post("/api/spaces/{space_id}/pause")
    def pause(space_id: str, user: User = You) -> dict[str, Any]:
        space = space_or_404(space_id, user)
        space.pause()
        return space.summary()

    @app.get("/api/spaces/{space_id}/events")
    def events(space_id: str, since: int = 0, user: User = You) -> list[dict[str, Any]]:
        space = space_or_404(space_id, user)
        return [
            {"seq": e.seq, "tick": e.tick, "kind": e.kind, **e.data}
            for e in space.runtime.log.since(since)
        ]

    @app.get("/api/spaces/{space_id}/stream")
    async def stream(
        space_id: str, request: Request, since: int = 0, user: User = You
    ) -> StreamingResponse:
        space = space_or_404(space_id, user)
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def push(event: Any) -> None:
            data = json.dumps(
                {"seq": event.seq, "tick": event.tick, "kind": event.kind, **event.data},
                default=str,
            )
            loop.call_soon_threadsafe(queue.put_nowait, data)

        with space.lock:  # no event can slip between the backlog and the live feed
            backlog = list(space.runtime.log.since(since))
            stop = space.runtime.log.listen(push)

        async def body():  # noqa: ANN202
            try:
                for event in backlog:
                    payload = {
                        "seq": event.seq,
                        "tick": event.tick,
                        "kind": event.kind,
                        **event.data,
                    }
                    yield f"data: {json.dumps(payload, default=str)}\n\n"
                while not await request.is_disconnected():
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {data}\n\n"
                    except TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                stop()

        return StreamingResponse(body(), media_type="text/event-stream")

    @app.get("/api/spaces/{space_id}/why/{node}/{belief}")
    def why(space_id: str, node: str, belief: str, user: User = You) -> dict[str, Any]:
        space = space_or_404(space_id, user)
        try:
            return space.why(node, belief)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.post("/api/spaces/{space_id}/approvals/{proposal}")
    def decide(space_id: str, proposal: str, body: Decision, user: User = You) -> dict[str, str]:
        space = space_or_404(space_id, user)
        try:
            return {"result": space.decide(proposal, body.approved)}
        except (KeyError, ValueError) as error:
            raise HTTPException(400, str(error)) from error

    # ---- recorded runs --------------------------------------------------------------------------

    @app.get("/api/runs")
    def runs(user: User = You) -> list[dict[str, Any]]:
        return [
            {
                "pack": pack.name,
                "path": r.path,
                "name": r.name,
                "options": r.options,
                "checks_passed": r.checks_passed,
                "checks_total": r.checks_total,
            }
            for pack in packs_for(user).values()
            for r in pack.recorded()
        ]

    class Replay(BaseModel):
        pack: str
        name: str
        options: dict[str, str] = {}
        model: str = "claude-haiku-5-5"

    @app.post("/api/runs/replay")
    def replay(body: Replay, user: User = You) -> dict[str, Any]:
        """Run a recorded case again with the same model: every request is in the model cache,
        so it costs nothing and gives the same run, now with everything open to inspect. The
        recorded runs are of simulated weeks, so their cache (the repository's) is shared."""
        pack = pack_or_404(body.pack, user)
        if body.name not in {r.name for r in pack.recorded()}:
            raise HTTPException(404, f"no recorded run {body.pack}/{body.name}")
        options = {k: v for k, v in body.options.items() if k != "model"}
        try:
            space = registry.create(
                pack,
                pack.team(body.name, {}),
                name=body.name,
                model=body.model,
                options=options,
                owner=user.id,
                cache=ROOT / "runs" / "cache",
                key=own_key(user),
            )
        except (ValueError, KeyError) as error:
            raise HTTPException(400, str(error)) from error
        space.play()
        return space.summary()

    app.include_router(connections_router())
    app.include_router(auth_router())

    # ---- the console ----------------------------------------------------------------------------

    if CONSOLE.exists():
        app.mount("/assets", StaticFiles(directory=CONSOLE / "assets", check_dir=False), "assets")

        @app.get("/")
        def index() -> FileResponse:
            return FileResponse(CONSOLE / "index.html")

    return app


app = create_app()


def main(host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="warning")


__all__ = ["app", "create_app", "main"]
