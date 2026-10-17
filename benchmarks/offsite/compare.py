"""The offsite, run twice on the same script: with the shared graph, and with shared notes.

    uv run python benchmarks/offsite/compare.py --provider anthropic --runs 3 --out runs/offsite

Same desks, goals, tools, model, token budget and checks; only memory differs (frame/notes.py).
Each run writes <out>/<memory>-r<n>.events.jsonl (every event, which the console replays) and a
.trace.jsonl (every model call). Requests are cached under runs/cache/<model>-offsite, so a rerun
is free. A side-by-side table goes to <out>/summary.md. `--max-input-tokens` stops the whole
comparison once that many input tokens have been sent (a spend cap).

With `--provider stand-in` only the graph side runs: the stand-in desks read the graph, so they
cannot stand in for a model reading notes.
"""

import argparse
import json
import os
import time
from pathlib import Path

from graph_agent.frame.notes import notes_team
from graph_agent.harness.llm import AnthropicClient, CachedClient, ModelClient
from graph_agent.harness.trace import Trace, TracedClient
from graph_agent.packs.offsite.run import run_offsite
from graph_agent.packs.offsite.standin import offsite_team as stand_in
from graph_agent.packs.offsite.teams import offsite_team

env_file = Path(__file__).parents[2] / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not line.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

parser = argparse.ArgumentParser()
parser.add_argument("--provider", choices=["anthropic", "stand-in"], default="anthropic")
parser.add_argument("--model", default="claude-haiku-5-5")
parser.add_argument("--memories", nargs="+", choices=["graph", "notes"], default=["graph", "notes"])
parser.add_argument("--runs", type=int, default=1, help="repeats (each is cached separately)")
parser.add_argument("--max-output-tokens", type=int, default=2000)
parser.add_argument("--max-input-tokens", type=int, default=0, help="stop after this many")
parser.add_argument("--out", default="runs/offsite")
args = parser.parse_args()

sent = [0]  # input tokens sent to the provider so far (cache hits are free and not counted)
if args.provider == "anthropic":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("put ANTHROPIC_API_KEY=... in .env and run again")
    real = AnthropicClient(
        args.model,
        os.environ["ANTHROPIC_API_KEY"],
        max_tokens=args.max_output_tokens,
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", ""),
    )
    complete = real.complete

    def capped(system, messages, tools):  # noqa: ANN001, ANN201
        if args.max_input_tokens and sent[0] >= args.max_input_tokens:
            raise SystemExit(f"stopped: {sent[0]} input tokens sent (cap {args.max_input_tokens})")
        reply = complete(system, messages, tools)
        sent[0] += reply.tokens_in
        return reply

    real.complete = capped  # type: ignore[method-assign]
else:
    args.memories = ["graph"]


def client_for(run: int) -> ModelClient:
    if args.provider == "stand-in":
        return stand_in()
    # each repeat has its own cache, so repeats are separate samples, not replays of the first
    return CachedClient(real, f"runs/cache/{args.model}-mt{args.max_output_tokens}-offsite-r{run}")


out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
rows = []
start = time.time()
for memory in args.memories:
    for n in range(1, args.runs + 1):
        team = offsite_team() if memory == "graph" else notes_team(offsite_team())
        name = f"{memory}-r{n}"
        trace = Trace(out / f"{name}.trace.jsonl")
        try:
            run = run_offsite(TracedClient(client_for(n), trace), team=team, trace=trace)
        finally:
            trace.close()
        with (out / f"{name}.events.jsonl").open("w") as f:
            for e in run.runtime.log.events:
                record = {"seq": e.seq, "tick": e.tick, "kind": e.kind, **e.data}
                f.write(json.dumps(record, default=str) + "\n")
        rows.append({"memory": memory, "run": n, **run.score, "checks": run.checks})
        print(
            f"{name}: {run.score['checks_passed']}/{run.score['checks_total']} checks, "
            f"{run.score['outward_actions']} actions, {run.score['tokens_in']} tokens in"
        )
        for check, ok in run.checks.items():
            print(f"   {'PASS' if ok else 'FAIL'} {check}")

(out / "results.json").write_text(json.dumps(rows, indent=2))
(out / "meta.json").write_text(json.dumps({"replayable": 2, "model": args.model}))
columns = [
    "memory",
    "run",
    "checks_passed",
    "checks_total",
    "outward_actions",
    "held_actions",
    "unsafe_proposals",
    "fake_quarantined",
    "honest_blamed",
    "tokens_in",
    "model_calls",
]
lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
lines += ["| " + " | ".join(str(row.get(c)) for c in columns) + " |" for row in rows]
checks = sorted({c for row in rows for c in row["checks"]})
lines += ["", "| check | " + " | ".join(f"{r['memory']} r{r['run']}" for r in rows) + " |"]
lines += ["|---|" + "---|" * len(rows)]
lines += [
    f"| {c} | " + " | ".join("pass" if r["checks"].get(c) else "FAIL" for r in rows) + " |"
    for c in checks
]
(out / "summary.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
print(f"{sent[0]} input tokens sent to the provider, {time.time() - start:.0f}s")
