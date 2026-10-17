// Pure helpers over a space's state and its event log: what was true at a given tick, and plain
// words for it. Nothing here knows any pack.
import type { TrailStep } from "../Graph";
import { LENSES } from "../lenses";
import type { BeliefView, Proposal, RunEvent, SpaceState, Why } from "../types";

export const LIVE = new Set(["active", "suspect"]);
export const DROPPED = new Set(["stale", "retracted", "superseded"]);

export function str(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** A belief's status at the end of `tick`, or null if it did not exist yet. */
export function statusAt(belief: BeliefView, tick: number): string | null {
  if (belief.born > tick) return null;
  let status = "active";
  for (const change of belief.history) if (change.tick <= tick) status = change.status;
  return status;
}

/** Where a belief came from, in a few words. */
/** Where a belief came from. `owns`: what the node keeps; an observation of anything else was a
 * check of something it was told, not something it watches. */
export function originText(b: BeliefView, owns: string[] = []): string {
  if (b.origin === "observed") return owns.length === 0 || owns.includes(b.subject) ? "seen directly" : "checked (it was told about this)";
  if (b.origin === "derived") return b.sources.length ? `from ${b.sources.join(", ")}` : "worked out";
  const route = b.routes[0];
  return route?.length ? `told by ${route[route.length - 1]}` : "told";
}

/** Who had stopped trusting whom by the end of `tick`: each exposure, less those taken back. */
export function distrustAt(events: RunEvent[], tick: number): { viewer: string; agent: string }[] {
  const out = new Map<string, { viewer: string; agent: string }>();
  for (const e of events) {
    if (e.tick > tick) continue;
    if (e.kind !== "exposure" && e.kind !== "reinstatement") continue;
    const pair = { viewer: str(e.viewer), agent: str(e.agent) };
    const key = `${pair.viewer}\u0000${pair.agent}`;
    if (e.kind === "exposure") out.set(key, pair);
    else out.delete(key);
  }
  return [...out.values()];
}

/** Outside senders that someone in the team had stopped trusting by the end of `tick`. */
export function quarantinedBy(events: RunEvent[], tick: number): Map<string, Set<string>> {
  const out = new Map<string, Set<string>>();
  for (const { viewer, agent } of distrustAt(events, tick)) {
    if (!out.has(agent)) out.set(agent, new Set());
    out.get(agent)!.add(viewer);
  }
  return out;
}

export interface TickStats {
  items: number;
  told: number; // messages believed
  bad: number; // messages not believed
  changes: number; // belief changes and trust cuts
  held: number;
  actions: number;
  turns: number;
}

export function tickStats(events: RunEvent[], tick: number): TickStats {
  const s: TickStats = { items: 0, told: 0, bad: 0, changes: 0, held: 0, actions: 0, turns: 0 };
  for (const e of events) {
    if (e.tick !== tick) continue;
    if (e.kind === "item") s.items++;
    else if (e.kind === "message") {
      if (e.believed) s.told++;
      else s.bad++;
    } else if (e.kind === "change" || e.kind === "exposure" || e.kind === "reinstatement") s.changes++;
    else if (e.kind === "held") s.held++;
    else if (e.kind === "action") s.actions++;
    else if (e.kind === "turn") s.turns++;
  }
  return s;
}

const lastPart = (reason: string) => reason.split(": ").slice(-1)[0] ?? reason;

/** One line on what mattered at this tick, picked from its events (like the Fire game's caption). */
export function caption(events: RunEvent[], tick: number): string {
  const here = events.filter((e) => e.tick === tick);
  const exposure = here.find((e) => e.kind === "exposure" && !str(e.reason).startsWith("quarantined by"));
  if (exposure) {
    const team = here.filter((e) => e.kind === "exposure" && e.agent === exposure.agent).length;
    return `${str(exposure.viewer)} catches ${str(exposure.agent)}: ${str(exposure.reason)}${team > 1 ? ` · ${team} nodes stop trusting it` : ""}`;
  }
  const held = here.filter((e) => e.kind === "held");
  if (held.length) return `${held.length} action${held.length > 1 ? "s" : ""} held: ${lastPart(str(held[0]!.reason))}`;
  const fanned = here.filter((e) => e.kind === "change" && str(e.reason).includes("withdrew"));
  if (fanned.length) {
    const nodes = [...new Set(fanned.map((e) => str(e.viewer)))];
    return `A correction reaches ${nodes.join(", ")}: ${lastPart(str(fanned[0]!.reason))}`;
  }
  const change = here.find((e) => e.kind === "change");
  if (change) return `${str(change.viewer)}: ${str(change.belief)} is now ${str(change.new)} (${str(change.reason)})`;
  const action = here.find((e) => e.kind === "action");
  if (action) return `${str(action.node)} ${action.status === "shadow" ? "would do" : "does"} ${str(action.tool)}: ${str(action.result)}`;
  const count = (kind: string) => here.filter((e) => e.kind === kind).length;
  const parts = [
    count("item") ? `${count("item")} item${count("item") > 1 ? "s" : ""} in` : "",
    count("turn") ? `${count("turn")} turn${count("turn") > 1 ? "s" : ""}` : "",
    count("message") ? `${count("message")} message${count("message") > 1 ? "s" : ""}` : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Nothing happened.";
}

/** The first tick after `tick` with an event matching `pred`. */
export function nextTick(events: RunEvent[], tick: number, last: number, pred: (e: RunEvent) => boolean): number | null {
  for (let t = tick + 1; t <= last; t++) if (events.some((e) => e.tick === t && pred(e))) return t;
  return null;
}

/** The gold trail of an open belief: the routes it came by, and where its copies went. */
export function trailOf(why: Why | null, tick: number): TrailStep[] {
  if (!why || tick < why.belief.born) return [];
  const steps: TrailStep[] = [];
  const cut = new Set(why.cut_by_distrust);
  for (const u of why.upstream) {
    const route = u.route?.length ? u.route : u.sender ? [u.sender] : [];
    const hops = [...route, why.viewer];
    for (let i = 0; i + 1 < hops.length; i++) steps.push({ from: hops[i]!, to: hops[i + 1]!, cut: cut.has(hops[i]!) });
  }
  for (const d of why.downstream) steps.push({ from: why.viewer, to: d.node, cut: DROPPED.has(d.status) });
  return steps;
}

/** A tool call in plain words, without the beliefs it names. */
export function callText(p: Pick<Proposal, "tool" | "arguments">): string {
  const args = Object.entries(p.arguments).filter(([k]) => k !== "depends_on");
  return `${p.tool}(${args.map(([k, v]) => `${k}=${str(v)}`).join(", ")})`;
}

/** One line of plain language for an event in the log. */
export function describe(e: RunEvent, state: SpaceState): string {
  const d = (k: string) => str(e[k]);
  switch (e.kind) {
    case "run_start": return `The team "${state.team.name}" starts.`;
    case "tick": return `— ${state.clocks[e.tick] ?? e.tick} begins —`;
    case "item": return `${[d("source"), ...((e.via as string[] | undefined) ?? [])].join(" → ")} → ${(e.to as string[] | undefined)?.join(", ") || "nobody"}: ${str((e.payload as Record<string, unknown> | undefined)?.subject) || d("item_kind")}`;
    case "message": return `${d("sender")} → ${d("receiver")}: ${e.text ? d("text") : `${d("subject")} ${d("predicate")} = ${d("value")}${e.detail ? `, ${d("detail")}` : ""}`}${e.believed ? "" : " (not believed: it came through someone it distrusts)"}`;
    case "turn": return `${d("node")} took a turn (${(e.calls as unknown[] | undefined)?.length ?? 0} tool calls): ${d("text")}`;
    case "tool": return `${d("node")} · ${d("tool")} → ${d("result").slice(0, 140)}`;
    case "change": return `${d("viewer")}: ${d("belief")} is now ${d("new")} (${d("reason")})`;
    case "exposure": return `${d("viewer")} stopped trusting ${d("agent")}: ${d("reason")}`;
    case "reinstatement": return `${d("viewer")} trusts ${d("agent")} again: ${d("reason")}`;
    case "warning": return `${d("sender")} warned ${d("receiver")} about ${d("accused")}`;
    case "proposal": return `${d("node")} proposes ${callText({ tool: d("tool"), arguments: (e.arguments as Record<string, unknown>) ?? {} })}`;
    case "decision": return `${d("id")} ${e.approved ? "approved" : "rejected"} by ${d("by")}`;
    case "action": return `${d("node")} ${e.status === "shadow" ? "would do" : "did"} ${d("tool")}: ${d("result")}`;
    case "held": return `HELD ${d("id")} ${d("tool")} of ${d("node")}: it rested on ${(e.broken as string[]).join(", ")}, which changed`;
    case "run_end": return "The run is over.";
    default: return (state.world.lens && LENSES[state.world.lens]?.describe(e)) || e.kind;
  }
}
