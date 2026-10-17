"""Belief "why" chains for the Cascade draft 2 card, from one graph-system trace log.

For every belief in the final snapshot: what supports it (routes), what it was derived from
(depends_on), which exposure cut its routes and why, who it was passed on to, and which
beliefs in other agents' memories came from those messages.

    python src/graph_agent/packs/ringfire/viewer/drafts/extract_why_draft2.py runs/hard16/logs/graph-memory_g0_n16_s0.jsonl > why.json
"""

import json
import re
import sys


def main(path: str) -> None:
    events = [json.loads(line) for line in open(path)]
    snap = [e for e in events if e["kind"] == "beliefs"]
    # Belief ids come from one global counter, so creation order is id order.
    order = sorted(snap, key=lambda e: int(e["belief"][1:]))

    born: dict[str, int] = {}
    deps: dict[str, list[str]] = {}
    sent: dict[str, list[list]] = {}
    for e in events:
        if e["kind"] != "tool_result" or e.get("error"):
            continue
        day = e["day"]
        args, result = e.get("arguments") or {}, str(e.get("result", ""))
        m = re.match(r"recorded (B\d+)", result)
        if e["tool"] == "assert_belief" and m:
            born[m[1]] = day
            deps[m[1]] = list(args.get("depends_on") or [])
        if e["tool"] == "send" and result.startswith("sent to") and args.get("belief_id"):
            sent.setdefault(args["belief_id"], []).append([day, args["to"]])

    # Imposters pass things on outside the toolbox; the engine logs those as imposter_relay.
    for e in events:
        if e["kind"] == "imposter_relay" and e["delivered"]:
            for b in snap:
                if (b["agent"] == f"A{e['imposter']}" and b["origin"] == "told"
                        and b["subject"] == f"F{e['field']}" and b["value"] == e["claim_day"]):
                    sent.setdefault(b["belief"], []).append([e["day"], f"A{e['to']}"])

    # Told beliefs are born on the day their message is delivered.
    msgs = [e for e in events if e["kind"] == "message" and not e.get("held")]
    for b in snap:
        if b["origin"] == "told":
            for route in b["routes"]:
                hit = [m["day"] for m in msgs if f"A{m['receiver']}" == b["agent"]
                       and m["field"] == int(b["subject"][1:]) and m["claim_day"] == b["value"]
                       and [f"A{x}" for x in m["route"]] == route]
                if hit:
                    born[b["belief"]] = min(hit + [born.get(b["belief"], 99)])
    # Remaining (observed) beliefs: the day of the nearest earlier id with a known day.
    last = 0
    for b in order:
        last = born.setdefault(b["belief"], last)

    cuts = [e for e in events if e["kind"] == "exposure"]
    out: dict[str, list[dict]] = {}
    for b in order:
        bid, agent = b["belief"], b["agent"]
        mine = [c for c in cuts if c["viewer"] == agent and any(c["distrusted"] in r for r in b["routes"])]
        stale = next((c["day"] for c in cuts if c["viewer"] == agent
                      and any(ch[0] == bid and ch[2] == "stale" for ch in c["changes"])), None)
        # Cross-agent: beliefs elsewhere whose route ends with this agent and carry the same claim.
        later = [{"agent": o["agent"], "id": o["belief"]} for o in snap
                 if o["origin"] == "told" and o["subject"] == b["subject"] and o["value"] == b["value"]
                 and any(r and r[-1] == agent for r in o["routes"])] if bid in sent else []
        out.setdefault(agent, []).append({
            "id": bid, "field": int(b["subject"][1:]), "value": b["value"], "origin": b["origin"],
            "status": b["status"], "routes": b["routes"], "born": born[bid], "stale": stale,
            "deps": deps.get(bid, []),
            "dependents": [k for k, v in deps.items() if bid in v],
            "cuts": [[c["day"], c["distrusted"], c["reason"]] for c in mine],
            "sent": sent.get(bid, []), "became": later, "true": b["claim_true"],
        })
    json.dump(out, sys.stdout, separators=(",", ":"))


if __name__ == "__main__":
    main(sys.argv[1])
