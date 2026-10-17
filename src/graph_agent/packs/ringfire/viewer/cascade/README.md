# Cascade viewer

Replays one Ring Fire game as played by several systems (say, the graph memory and a prompt-only
baseline): what the agents told each other, what each was thinking, and, for graph systems, why
each belief holds or was dropped (its routes, the trust cuts that killed them, what was derived from
it, and where it went next).

React + TypeScript, built into one self-contained HTML file. The Python side fills it with data:

```python
from graph_agent.packs.ringfire.benchmark.cascade import cascade_data, write_viewer

data = cascade_data({"graph memory": "runs/x/logs/graph-memory_g0_n16_s0.jsonl",
                     "prompt only": "runs/x/logs/B3o_g0_n16_s0.jsonl"})
write_viewer(data, "runs/x/cascade.html")   # opens by double-click
```

## Working on the page

```sh
cd src/graph_agent/packs/ringfire/viewer/cascade
npm install
npm run dev        # loads public/sample.json: write one with json.dump(cascade_data(...), ...)
npm test           # model.ts unit tests
npm run build      # type-check, build, and copy the page to src/graph_agent/packs/ringfire/viewer/cascade.html
```

`src/graph_agent/packs/ringfire/viewer/cascade.html` is the built page and is committed, so making pages from Python needs no
Node. Rebuild it after changing anything here.

## Layout

- `src/types.ts`: the data's shape. It mirrors the TypedDicts in
  `src/graph_agent/packs/ringfire/benchmark/cascade.py`; change both together.
- `src/model.ts`: everything derived from the data (field states, a belief's status on a day,
  captions, where the page opens). No React, so it is unit-tested on its own.
- `src/components/`: `Timeline`, `Network` (the agents on a ring, today's messages, trust cuts, the
  open belief's trail), `AgentCard` (thinking, chat, beliefs and their chains), `World` (the
  ground truth no agent sees).
- `src/cypher.ts`: the FalkorDB queries shown next to each step of a belief's chain.
