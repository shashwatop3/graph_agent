# graph-agent

A domain-agnostic graph layer that keeps the beliefs of several LLM agents consistent when a
correction arrives, plus a benchmark game (Ring Fire) that runs the same agents on two backends:
a graph store (FalkorDB) and a relational store (PostgreSQL).

Status: stages S0 to S13 built (everything in the plan except a real language model and the runs with it). No real model is connected yet.
`docs` symlink in this folder (not tracked by git).

## Layout

The main project is generic. Domains are packs on top of it; Ring Fire (the benchmark game) is one
pack, loaded into the console like any other.

| Path | Purpose | May import |
|---|---|---|
| `src/graph_agent/core/` | The belief graph: nodes, edges, store interface, context compiler, graph tools | itself only |
| `src/graph_agent/stores/` | In-memory, FalkorDB and PostgreSQL stores | core |
| `src/graph_agent/harness/` | Model client and cache, one agent turn, run trace | core |
| `src/graph_agent/frame/` | A team of nodes (triggers, a model or code handler, own tools, graph tools), the runtime, MCP client, what a pack gives the console | core, harness |
| `src/graph_agent/service/` | HTTP API with a live event stream, and the list of packs the page offers | everything above |
| `src/graph_agent/packs/ringfire/` | The fire game: `sim/` engine, `adapter.py`, `benchmark/` (original loop, baselines, scoring), `pack.py` (on the frame), `viewer/` | core, stores, harness, frame |
| `src/graph_agent/packs/life/` | Mail, calendar, travel, promises, money: a simulated week, tools, teams, MCP server | core, stores, harness, frame |
| `src/graph_agent/packs/hualien/` | The Hualien earthquake adapter (real data, second domain) | core |
| `viewer/console/` | The page: build a team on a canvas, run it, see why | n/a |
| `benchmarks/` | Run scripts: `ringfire/`, `life/`, and the store micro-benchmark | n/a |
| `tests/` | Tests: shared at the top, per pack in `ringfire/`, `life/`, `hualien/` | n/a |

To add a pack: a folder under `packs/` that implements `frame/console.py:ConsolePack`, listed in
`service/registry.py`. `tests/test_architecture.py` enforces the import rules, keeps domain words
out of the generic packages, keeps packs from importing each other and keeps `ringfire/sim` free of
imports.

## Setup

Requirements: Docker with Compose, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # installs Python 3.12 and dependencies
docker compose up -d --wait  # FalkorDB and PostgreSQL
uv run pytest                # all tests
uv run pytest -m "not integration"   # without the databases
uv run ruff check .
```

Services (bound to 127.0.0.1, off the default ports):

| Service | Port | Notes |
|---|---|---|
| FalkorDB | 16379 | Redis protocol. Browser UI at http://127.0.0.1:13000 |
| PostgreSQL | 15432 | user `postgres`, password `postgres`, database `graph_agent` (local only) |

Override with `FALKORDB_HOST`, `FALKORDB_PORT` and `POSTGRES_DSN`.

## The frame, the use cases and the console

```bash
uv sync --extra service                      # FastAPI, uvicorn and the MCP SDK
(cd viewer/console && npm install && npm run build)
uv run python -m graph_agent.service         # the console at http://127.0.0.1:8765
uv run python benchmarks/ringfire/frame_pilot.py --provider anthropic --systems frame-memory ...
uv run python benchmarks/life/run.py --provider anthropic --cases travel promises money week
uv run python -m graph_agent.packs.life.mcp_server   # the simulated services as an MCP server
```

Ring Fire on the frame plays exactly the game of `harness/game.py` (`tests/test_frame_ringfire.py`
compares the logs event for event), so the two share a model cache.

## Your real accounts (read-only mail, Todoist)

The life pack's "Real mailbox" team reads your Gmail and Calendar and plans Todoist tasks from
promises in your mail. It uses ready-made MCP servers ([workspace-mcp] for Google, Doist's
`@doist/todoist-mcp` for Todoist); we wrote no connectors. Mail and calendar are read-only, and
Todoist writes are only recorded ("shadow") unless you choose otherwise.

```
# .env (values are never printed)
GOOGLE_OAUTH_CLIENT_ID=...        # also read as GOOGLE_CLIENT_API
GOOGLE_OAUTH_CLIENT_SECRET=...    # also read as GOOGLE_CLIENT_SECRET
USER_GOOGLE_EMAIL=you@gmail.com
TODOIST_API_KEY=...
uv run python -m graph_agent.packs.life.real auth   # once: prints a link, you sign in
```
Then pick "Real mailbox" in the console, leave "Outward actions" on "Record only", press Step.

[workspace-mcp]: https://github.com/taylorwilsdon/google_workspace_mcp
