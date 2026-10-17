"""Run a small sweep against a real model served locally (or anywhere OpenAI-compatible).

    uv run python benchmarks/ringfire/pilot.py --systems graph-memory B0 --agents 6 --seeds 0

Every request is cached under runs/cache/<model>, so rerunning the same sweep is instant and free.
Results go to runs/pilot/ (results.json, results.csv, summary.md).
"""

import argparse
import os
import time
from pathlib import Path

from graph_agent.harness.llm import AnthropicClient, CachedClient, OpenAICompatibleClient
from graph_agent.packs.ringfire.benchmark.experiment import Knobs, run_experiment

# a plain KEY=value file, kept out of git, so the key never goes in a command or in chat
env_file = Path(__file__).parents[2] / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not line.startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

parser = argparse.ArgumentParser()
parser.add_argument("--systems", nargs="+", default=["graph-falkor", "B1"])
parser.add_argument("--agents", type=int, nargs="+", default=[6])
parser.add_argument("--seeds", type=int, nargs="+", default=[0])
parser.add_argument("--behaviour", default="false_alarm")
# how hard the game is: every knob of experiment.Knobs
parser.add_argument("--fields-per-agent", type=int, default=1)
parser.add_argument("--initial-fires", type=int, default=1, help="fields burning at the start")
parser.add_argument("--hidden-edges", type=int, default=0)
parser.add_argument("--imposters", type=int, default=1)
parser.add_argument("--colluders", type=int, default=0)
parser.add_argument("--extra-links", type=int, default=0)
parser.add_argument(
    "--water",
    type=lambda v: None if v == "none" else int(v),
    default=2,
    help="waterings per agent, or 'none' for no limit",
)
parser.add_argument("--cooldown", type=int, default=1, help="days to rest after watering")
parser.add_argument(
    "--waste-penalty", type=float, default=0.0, help="a wasted watering, in burnt fields"
)
# the long game
parser.add_argument("--horizon", type=int, default=None, help="days the game lasts")
parser.add_argument(
    "--random-fire-chance", type=float, default=0.0, help="per day (needs --horizon)"
)
parser.add_argument("--regrow-days", type=int, default=None, help="burnt fields grow back after")
parser.add_argument("--probe-days", type=int, nargs="+", default=[2, 4])
parser.add_argument(
    "--no-contexts", action="store_true", help="leave the agents' contexts out of the log"
)
parser.add_argument("--log", default="", help="log directory (default: <out>/logs)")
parser.add_argument("--provider", choices=["local", "anthropic"], default="local")
parser.add_argument("--model", default="")
parser.add_argument(
    "--max-output-tokens",
    type=int,
    default=2000,
    help="per reply; a cut-off reply loses its tool call",
)
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
        max_tokens=args.max_output_tokens,
        workspace_id=os.environ.get("ANTHROPIC_WORKSPACE_ID", ""),
    )
else:
    args.model = args.model or "qwen3-14b"
    real = OpenAICompatibleClient(args.model, args.url, os.environ.get(args.key_env, ""))
# the cache key does not include the output cap, so each cap gets its own cache: a reply cut off
# at a small cap must not be served to a run with a bigger one
client = CachedClient(real, f"runs/cache/{args.model}-mt{args.max_output_tokens}")


def guarded(inner, cap):
    """Refuse further real requests once `cap` input tokens have been paid for."""
    complete = inner.complete

    def wrapper(system, messages, tools):
        if cap and client.tokens_in >= cap:
            raise SystemExit(f"stopped: {client.tokens_in} input tokens reached the cap of {cap}")
        return complete(system, messages, tools)

    inner.complete = wrapper


guarded(real, args.max_input_tokens)
grid = [
    Knobs(
        n_agents=n,
        fields_per_agent=args.fields_per_agent,
        initial_fires=args.initial_fires,
        hidden_edges=args.hidden_edges,
        imposters=args.imposters,
        behaviour=args.behaviour,
        colluders=args.colluders,
        extra_links=args.extra_links,
        water_per_agent=args.water,
        water_cooldown=args.cooldown,
        horizon=args.horizon,
        random_fire_chance=args.random_fire_chance,
        regrow_days=args.regrow_days,
        waste_penalty=args.waste_penalty,
    )
    for n in args.agents
]

start = time.time()
rows = run_experiment(
    args.systems,
    grid,
    args.seeds,
    lambda system, knobs: client,
    probe_days=tuple(args.probe_days),
    out_dir=args.out,
    log_dir=args.log or f"{args.out}/logs",
    log_contexts=not args.no_contexts,
)
print(open(f"{args.out}/summary.md").read())
print(
    f"{client.calls_made} real calls, {client.cache_hits} cached, "
    f"{client.tokens_in} tokens in, {client.tokens_out} out, {time.time() - start:.0f}s"
)
