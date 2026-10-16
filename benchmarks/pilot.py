"""Run a small sweep against a real model served locally (or anywhere OpenAI-compatible).

    uv run python benchmarks/pilot.py --systems graph-memory B0 --agents 6 --seeds 0

Every request is cached under runs/cache/<model>, so rerunning the same sweep is instant and free.
Results go to runs/pilot/ (results.json, results.csv, summary.md).
"""

import argparse
import os
import time

from graph_agent.harness.experiment import Knobs, run_experiment
from graph_agent.harness.llm import CachedClient, OpenAICompatibleClient

parser = argparse.ArgumentParser()
parser.add_argument("--systems", nargs="+", default=["graph-memory", "B0"])
parser.add_argument("--agents", type=int, nargs="+", default=[6])
parser.add_argument("--seeds", type=int, nargs="+", default=[0])
parser.add_argument("--behaviour", default="false_alarm")
parser.add_argument("--model", default="qwen3-14b")
parser.add_argument("--url", default="http://127.0.0.1:18080/v1")
parser.add_argument("--key-env", default="", help="name of the env var holding an API key")
parser.add_argument("--out", default="runs/pilot")
args = parser.parse_args()

real = OpenAICompatibleClient(args.model, args.url, os.environ.get(args.key_env, ""))
client = CachedClient(real, f"runs/cache/{args.model}")
grid = [Knobs(n_agents=n, behaviour=args.behaviour) for n in args.agents]

start = time.time()
rows = run_experiment(
    args.systems, grid, args.seeds, lambda system, knobs: client, out_dir=args.out
)
print(open(f"{args.out}/summary.md").read())
print(
    f"{client.calls_made} real calls, {client.cache_hits} cached, "
    f"{client.tokens_in} tokens in, {client.tokens_out} out, {time.time() - start:.0f}s"
)
