"""Run the life teams over the simulated week with a real model, and score them.

    uv run python benchmarks/life/run.py --provider anthropic --cases travel promises money week \
        --extraction model --out runs/life

Each run writes <out>/<case>-<extraction>.events.jsonl (every event: items, turns with the model's
text and tool calls, messages, changes, held actions, exposures, the score), which the console
replays, and <out>/<case>-<extraction>.trace.jsonl (every model call). Requests are cached under
runs/cache/<model>-life, so a rerun is free. A summary table goes to <out>/summary.md.
"""

import argparse
import json
import os
import time
from pathlib import Path

from graph_agent.harness.llm import AnthropicClient, CachedClient, OpenAICompatibleClient
from graph_agent.harness.trace import Trace, TracedClient
from graph_agent.packs.life.run import run_life

env_file = Path(__file__).parents[2] / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not line.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

parser = argparse.ArgumentParser()
parser.add_argument("--cases", nargs="+", default=["travel", "promises", "money"])
parser.add_argument("--extraction", choices=["gold", "model"], nargs="+", default=["model"])
parser.add_argument("--provider", choices=["local", "anthropic"], default="anthropic")
parser.add_argument("--model", default="")
parser.add_argument("--url", default="http://127.0.0.1:18080/v1")
parser.add_argument("--max-output-tokens", type=int, default=2000)
parser.add_argument("--max-input-tokens", type=int, default=0, help="stop after this many")
parser.add_argument("--out", default="runs/life")
args = parser.parse_args()

if args.provider == "anthropic":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("put ANTHROPIC_API_KEY=... in .env and run again")
    args.model = args.model or "claude-haiku-5-5"
    real = AnthropicClient(
        args.model,
        os.environ["ANTHROPIC_API_KEY"],
        max_tokens=args.max_output_tokens,
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", ""),
    )
else:
    args.model = args.model or "qwen3-14b"
    real = OpenAICompatibleClient(args.model, args.url)
client = CachedClient(real, f"runs/cache/{args.model}-mt{args.max_output_tokens}-life")
complete = real.complete


def capped(system, messages, tools):  # noqa: ANN001, ANN201
    if args.max_input_tokens and client.tokens_in >= args.max_input_tokens:
        raise SystemExit(f"stopped: {client.tokens_in} input tokens reached the cap")
    return complete(system, messages, tools)


real.complete = capped  # type: ignore[method-assign]
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
rows = []
start = time.time()
for case in args.cases:
    for extraction in args.extraction:
        name = f"{case}-{extraction}"
        trace = Trace(out / f"{name}.trace.jsonl")
        try:
            run = run_life(case, TracedClient(client, trace), extraction=extraction, trace=trace)
        finally:
            trace.close()
        with (out / f"{name}.events.jsonl").open("w") as f:
            for e in run.runtime.log.events:
                f.write(
                    json.dumps(
                        {"seq": e.seq, "tick": e.tick, "kind": e.kind, **e.data}, default=str
                    )
                    + "\n"
                )
        rows.append({"case": case, "extraction": extraction, **run.score, "checks": run.checks})
        print(
            f"{name}: {run.score['checks_passed']}/{run.score['checks_total']} checks, "
            f"{run.score['unsafe_proposals']} unsafe, {run.score['tokens_in']} tokens in"
        )
        for check, ok in run.checks.items():
            print(f"   {'PASS' if ok else 'FAIL'} {check}")

(out / "results.json").write_text(json.dumps(rows, indent=2))
# runs made with this version render every prompt the same on a replay, so the console can
# replay them from the cache for free (older runs printed tool arguments in the model's order)
(out / "meta.json").write_text(json.dumps({"replayable": 2, "model": args.model}))
columns = [
    "case",
    "extraction",
    "checks_passed",
    "checks_total",
    "unsafe_proposals",
    "honest_quarantined",
    "quarantined",
    "held_actions",
    "actions_done",
    "extraction_recall",
    "extraction_precision",
    "tokens_in",
    "model_calls",
]
lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
for row in rows:
    cells = []
    for c in columns:
        v = row.get(c)
        cells.append(f"{v:.2f}" if isinstance(v, float) else str(v))
    lines.append("| " + " | ".join(cells) + " |")
(out / "summary.md").write_text("\n".join(lines) + "\n")
print("\n".join(lines))
print(
    f"{client.calls_made} real calls, {client.cache_hits} cached, {client.tokens_in} tokens in, "
    f"{client.tokens_out} out, {time.time() - start:.0f}s"
)
