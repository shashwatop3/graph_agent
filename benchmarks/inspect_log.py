"""Read a run log written with --log (see src/graph_agent/harness/trace.py).

    uv run python benchmarks/inspect_log.py runs/x/logs/graph-memory_g0_n12_s0.jsonl
    uv run python benchmarks/inspect_log.py LOG --day 4 --agent A3     # one turn in full
    uv run python benchmarks/inspect_log.py LOG --kind exposure        # every event of one kind

With no filter it prints a summary: problems first (tool errors, turns that ran out of steps,
wrong probe answers, false beliefs still held), then a day-by-day timeline.
"""

import argparse
import json
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("log")
parser.add_argument("--day", type=int)
parser.add_argument("--agent")
parser.add_argument("--kind")
args = parser.parse_args()

events = [json.loads(line) for line in Path(args.log).read_text().splitlines() if line]


def show(event: dict) -> None:
    rest = {k: v for k, v in event.items() if k not in ("t", "kind")}
    context = rest.pop("context", None)
    print(f"[{event['t']:8.1f}s] {event['kind']:<14} {json.dumps(rest, default=str)}")
    if context:
        print("    ---- context ----\n" + "\n".join("    " + ln for ln in context.splitlines()))


if args.day is not None or args.agent or args.kind:
    for e in events:
        if args.day is not None and e.get("day") != args.day:
            continue
        if args.agent and e.get("agent") != args.agent:
            continue
        if args.kind and e["kind"] != args.kind:
            continue
        show(e)
    raise SystemExit

start = next(e for e in events if e["kind"] == "game_start")
print(f"{start['system']}  model={start['model']}  imposters={start['imposters']}")
print("events:", dict(Counter(e["kind"] for e in events)))

calls = [e for e in events if e["kind"] == "model_call"]
print(
    f"model calls: {len(calls)} ({sum(e['cached'] for e in calls)} cached), "
    f"{sum(e['tokens_in'] for e in calls)} tokens in, {sum(e['tokens_out'] for e in calls)} out, "
    f"{sum(e['seconds'] for e in calls if not e['cached']):.0f}s waiting"
)

print("\n== problems ==")
cut = [e for e in calls if e.get("stop_reason") in ("max_tokens", "length")]
print(f"replies cut off by the output cap: {len(cut)} of {len(calls)}")
errors = [e for e in events if e["kind"] == "tool_result" and e["error"]]
print(f"tool errors: {len(errors)}  by tool: {dict(Counter(e['tool'] for e in errors))}")
for e in errors[:8]:
    print(f"  day {e['day']} {e['agent']} {e['tool']}({e['arguments']}) -> {e['result']}")
capped = [e for e in events if e["kind"] == "turn_end" and e["hit_step_cap"]]
print(f"turns that ran out of steps: {len(capped)}", [(e["day"], e["agent"]) for e in capped[:10]])
silent = [e for e in events if e["kind"] == "turn_end" and e["tool_calls"] == 0]
print(f"turns with no tool call: {len(silent)} of {sum(e['kind'] == 'turn_end' for e in events)}")
wrong = [e for e in events if e["kind"] == "probe_scored" and not e["correct"]]
print(f"wrong probe answers: {len(wrong)} of {sum(e['kind'] == 'probe_scored' for e in events)}")
for e in wrong[:8]:
    who = f"{e['agent']} F{e['field']}"
    print(f"  asked day {e['asked_day']} {who}: said {e['answer']}, truth {e['truth']}")
bad = [
    e
    for e in events
    if e["kind"] == "beliefs" and e["claim_true"] is False and e["status"] in ("active", "suspect")
]
print(f"false beliefs still held: {len(bad)}")
for e in bad[:8]:
    what = f"{e['belief']} {e['subject']} day {e['value']} ({e['origin']})"
    print(f"  {e['agent']} {what}, routes {e['routes']}")

print("\n== timeline ==")
for e in events:
    k = e["kind"]
    if k == "day_start":
        print(f"day {e['day']}")
    elif k == "message" and not e["held"]:  # a held message is logged again when delivered
        flag = " ALTERED" if e["altered_by"] else ""
        print(f"  A{e['sender']} -> A{e['receiver']}: F{e['field']} on day {e['claim_day']}{flag}")
    elif k == "action":
        print(f"  {e['agent']} act {e['type']} {e['target'] or ''}: {e['reply']}")
    elif k == "exposure":
        print(f"  {e['viewer']} distrusts {e['distrusted']} ({e['reason']}): {e['changes']}")
    elif k == "day_end":
        print(f"  end: fire reached {[i[0] for i in e['ignited']]}, burnt out {e['burnt_out']}")
score = next((e for e in events if e["kind"] == "score"), None)
if score:
    print("\n== score ==")
    print({k: v for k, v in score.items() if k not in ("t", "kind", "day", "agent")})
elif any(e["kind"] == "aborted" for e in events):
    print("\nABORTED:", next(e for e in events if e["kind"] == "aborted")["error"])
