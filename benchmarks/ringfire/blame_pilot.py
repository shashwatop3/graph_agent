"""Who gets blamed for a lie: the same Ring Fire games under each blame rule, with the free
stand-in players (honest agents that pass on everything they hear).

    uv run python benchmarks/ringfire/blame_pilot.py --seeds 1 2 3 4 5 6 7 8 9 10

For every seed and rule it plays the game and counts, over the honest agents: how many were
wrongly distrusted by another honest agent (at the end, and at any time), how many of the
imposters were caught, and how many fields were saved.
"""

import argparse
from statistics import mean

from graph_agent.frame.events import EventLog
from graph_agent.packs.ringfire.console import RingFireConsole
from graph_agent.stores.memory import MemoryStore

RULES = {
    "direct_teller": {"blame": "direct_teller"},
    "direct_teller + repair": {"blame": "direct_teller", "repair": True},
    "first_hop": {"blame": "first_hop"},
    "first_hop + repair": {"blame": "first_hop", "repair": True},
}

parser = argparse.ArgumentParser()
parser.add_argument("--seeds", type=int, nargs="+", default=list(range(1, 11)))
parser.add_argument("--agents", type=int, default=8)
parser.add_argument("--imposters", type=int, default=2)
parser.add_argument("--extra-links", type=int, default=1)
parser.add_argument("--behaviour", default="false_alarm", help="what the imposters do")
args = parser.parse_args()

pack = RingFireConsole()
print(f"{args.agents} agents, {args.imposters} imposters ({args.behaviour}), seeds {args.seeds}\n")
print(f"{'rule':24} {'honest blamed (end)':>20} {'(ever)':>8} {'liars caught':>13} {'saved':>7}")
for name, knobs in RULES.items():
    rows = []
    for seed in args.seeds:
        options = {
            "seed": seed,
            "n_agents": args.agents,
            "imposters": args.imposters,
            "behaviour": args.behaviour,
            "extra_links": args.extra_links,
            **knobs,
        }
        team = pack.team("ringfire", options)
        session = pack.start(team, pack.stand_in(team), MemoryStore(), EventLog(), {})
        session.runtime.run()
        rows.append(session.score())
    print(
        f"{name:24} {mean(r['honest_blamed'] for r in rows):>20.2f}"
        f" {mean(r['honest_blamed_ever'] for r in rows):>8.2f}"
        f" {mean(r['liars_caught'] for r in rows):>13.2f}"
        f" {mean(r['fields_saved'] for r in rows):>7.2f}"
    )
