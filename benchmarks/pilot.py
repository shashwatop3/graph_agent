"""Run a small sweep against a real model served locally (or anywhere OpenAI-compatible).

    uv run python benchmarks/pilot.py --systems graph-memory B0 --agents 6 --seeds 0

Every request is cached under runs/cache/<model>, so rerunning the same sweep is instant and free.
Results go to runs/pilot/ (results.json, results.csv, summary.md).
"""

import argparse
import os
import time
from pathlib import Path

from graph_agent.harness.experiment import Knobs, run_experiment
from graph_agent.harness.llm import AnthropicClient, CachedClient, OpenAICompatibleClient

# a plain KEY=value file, kept out of git, so the key never goes in a command or in chat
env_file = Path(__file__).parent.parent / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not line.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

parser = argparse.ArgumentParser()
parser.add_argument("--systems", nargs="+", default=["graph-memory", "B0"])
parser.add_argument("--agents", type=int, nargs="+", default=[6])
parser.add_argument("--seeds", type=int, nargs="+", default=[0])
parser.add_argument("--behaviour", default="false_alarm")
parser.add_argument("--provider", choices=["local", "anthropic"], default="local")
parser.add_argument("--model", default="")
parser.add_argument(
    "--max-input-tokens", type=int, default=0, help="stop after this many (0=no cap)"
)
parser.add_argument("--url", default="http://127.0.0.1:18080/v1")
parser.add_argument("--key-env", default="", help="name of the env var holding an API key")
parser.add_argument("--out", default="runs/pilot")
args = parser.parse_args()

if args.provider == "anthropic":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("put ANTHROPIC_API_KEY=... in .env (see README) and run again")
    args.model = args.model or "claude-haiku-5-5"
    real = AnthropicClient(
        args.model,
        os.environ["ANTHROPIC_API_KEY"],
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", ""),
    )
else:
    args.model = args.model or "qwen3-14b"
    real = OpenAICompatibleClient(args.model, args.url, os.environ.get(args.key_env, ""))
client = CachedClient(real, f"runs/cache/{args.model}")


def guarded(inner, cap):
    """Refuse further real requests once `cap` input tokens have been paid for."""
    complete = inner.complete

    def wrapper(system, messages, tools):
        if cap and client.tokens_in >= cap:
            raise SystemExit(f"stopped: {client.tokens_in} input tokens reached the cap of {cap}")
        return complete(system, messages, tools)

    inner.complete = wrapper


guarded(real, args.max_input_tokens)
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
