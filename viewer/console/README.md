# Groundwork (the console)

Build a team of agent nodes on a canvas, run it, and watch it the way the Fire game showed Ring
Fire: a timeline with an activity strip, the team network with a floating card for the open node,
and a separate side screen with the state of things. The look (tokens, timeline, card, chat,
why-chain) is the Fire game's, from `src/graph_agent/packs/ringfire/viewer/cascade`.

## Run it

```sh
uv sync --extra service                     # FastAPI, uvicorn, the MCP SDK
cd viewer/console && npm install && npm run build && cd -
uv run python -m graph_agent.service        # http://127.0.0.1:8765
```

For development keep the service running and use `npm run dev` here (Vite proxies `/api`).
`npm test` runs the unit tests (vitest), `npm run typecheck` the types.

## Build (`src/build/`)

- **Canvas** (left): the team as a graph, discs as in the Fire game. Drag to arrange, click to edit,
  Delete removes the selected node or link, Esc clears. **Link** draws *talks to*, *feeds* or
  *watches* (click one node, then the other); click a line to change or delete it. **Tidy** lays
  the team out again. Your work is kept in this browser as a draft.
- **Side screen** (right), four tabs: **Teams** (each pack's ready-made teams, a blank team, export
  and import of the team file), **Add** (the node catalogue), **Edit** (the selected node's role,
  instructions, triggers, own tools, ownership and links; or the selected link), **Team** (name,
  ticks, budget, trust settings).
- **Top bar**: the model (free stand-in, or Claude Haiku through the cache), the store (in memory
  or FalkorDB, kept), the pack's own options (for life: outward actions at once, waiting for you,
  or recorded only; mail read by a connector or a model), and **Run this team**.

## Run (`src/run/`)

- **Timeline** (`Timeline.tsx`): ◂ ▶ ▸ replay the ticks played so far; **Step** plays one more tick
  on the server, **Run** plays to the end; jump to the next correction or held action; a caption
  written from the tick's events; a strip of every tick (items read, messages, not believed,
  corrections and trust cuts, held actions). Click the strip or use the arrow keys.
- **Team network** (`Network.tsx`, `../Graph.tsx`): who took a turn (filled disc), messages with
  comets, items from outside senders (struck out in red once quarantined), trust cuts, actions held
  (gold ring), and the open belief's gold trail along its routes and copies. The counters show
  held actions and quarantined senders.
- **Node card** (`AgentCard.tsx`), beside the open node: its thinking (typed out), its tool calls
  and the context it read (its whole memory, compiled from the graph), the tick's chat, its
  beliefs (tap one for the why-chain: source or routes, what it rests on, every change and why,
  what rests on it, copies in other nodes, actions resting on it, the FalkorDB queries, run live
  with timings on FalkorDB), its actions and whom it no longer trusts.
- **Side screen** (`Side.tsx`): **World** (the pack's lens, `src/lenses/`), **Actions** (approve or
  reject, held, recorded), **Memory** (each node's beliefs at the tick), **Log** (every event).

## Runs

This session's runs, and recorded real-model runs replayed from the model cache at no cost.

The API it talks to is documented at the top of `src/graph_agent/service/app.py`. A pack draws its
world with a lens in `src/lenses/` named by `world.lens`; everything else in the page is generic.
