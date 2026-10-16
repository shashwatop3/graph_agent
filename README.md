# graph-agent

A domain-agnostic graph layer that keeps the beliefs of several LLM agents consistent when a
correction arrives, plus a benchmark game (Ring Fire) that runs the same agents on two backends:
a graph store (FalkorDB) and a relational store (PostgreSQL).

Status: stages S0 to S4 done (skeleton, fire engine, messages and oracle, core model, FalkorDB store). Design notes live in the Obsidian vault and are reachable through the
`docs` symlink in this folder (not tracked by git).

## Layout

| Path | Purpose | May import |
|---|---|---|
| `src/graph_agent/core/` | Generic layer, no domain vocabulary | itself only |
| `src/graph_agent/stores/` | FalkorDB and PostgreSQL implementations of the store interface | core |
| `src/graph_agent/adapters/` | Per-domain code (Ring Fire, later Hualien) | core |
| `src/graph_agent/sim/` | Game engine and oracle | itself only |
| `src/graph_agent/harness/` | Run loop, agents, cache, scoring | everything |
| `viewer/` | Replay page (later stage) | n/a |
| `tests/` | Tests | n/a |

`tests/test_architecture.py` enforces these import rules and checks the core for domain words.

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
