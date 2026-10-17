// Everything the page derives from the data, as plain functions of (run, day). No React here, so
// it can be tested on its own (model.test.ts).

import type { BeliefView, CascadeData, MessageView, RunView, ScenarioView } from "./types";

export const A = (i: number) => `A${i}`;
export const owner = (s: ScenarioView, field: number) => Math.floor(field / s.fields_per_agent);
export const isImposter = (s: ScenarioView, agent: number) => String(agent) in s.imposters;
export const lastDay = (run: RunView) => run.days.length - 1;
export const hasBeliefs = (run: RunView) => Object.keys(run.beliefs).length > 0;

// ---- the world ---------------------------------------------------------------------------------

export type FieldState = "alive" | "burning" | "burnt" | "saved";

/** Each field's state at the end of `day`; fields not listed are alive. */
export function worldAt(run: RunView, day: number): Map<number, FieldState> {
  const state = new Map<number, FieldState>();
  for (const d of run.days.slice(0, day + 1)) {
    d.ignited.forEach((f) => state.set(f, "burning"));
    d.burnt_out.forEach((f) => state.set(f, "burnt"));
    d.saved.forEach((f) => state.set(f, "saved"));
    d.regrown.forEach((f) => state.delete(f));
  }
  return state;
}

export interface DayStats {
  fire: number;
  lies: number;
  truth: number;
  cuts: number;
}

export function dayStats(run: RunView, day: number): DayStats {
  const fire = [...worldAt(run, day).values()].filter((s) => s === "burning").length;
  const sent = run.messages.filter((m) => m.day === day);
  const lies = sent.filter((m) => m.altered).length;
  return { fire, lies, truth: sent.length - lies, cuts: run.exposures.filter((e) => e.day === day).length };
}

/** Lies honest agents passed on, up to and including `day`: the number the comparison is about. */
export function liesPassedOn(s: ScenarioView, run: RunView, day: number): MessageView[] {
  return run.messages.filter((m) => m.day <= day && m.altered && !isImposter(s, m.sender));
}

/** One line for the timeline, built from what happened that day. */
export function caption(s: ScenarioView, run: RunView, day: number): string {
  const d = run.days[day];
  if (!d) return "";
  const fields = (fs: number[]) => fs.map((f) => `F${f}`).join(", ");
  const parts: string[] = [];
  if (d.ignited.length) parts.push(`${fields(d.ignited)} ${d.ignited.length > 1 ? "catch" : "catches"} fire`);
  const sent = run.messages.filter((m) => m.day === day);
  const lies = sent.filter((m) => m.altered);
  if (sent.length)
    parts.push(`${sent.length} report${sent.length > 1 ? "s" : ""} sent${lies.length ? `, ${lies.length} of them false` : ""}`);
  const relayed = [...new Set(lies.filter((m) => !isImposter(s, m.sender)).map((m) => A(m.sender)))];
  if (relayed.length) parts.push(`${relayed.join(", ")} ${relayed.length > 1 ? "pass" : "passes"} a lie on`);
  const cuts = run.exposures.filter((e) => e.day === day);
  if (cuts.length) parts.push(`${cuts.length} trust cut${cuts.length > 1 ? "s" : ""}`);
  if (d.saved.length) parts.push(`${fields(d.saved)} saved by water`);
  if (d.burnt_out.length) parts.push(`${fields(d.burnt_out)} ${d.burnt_out.length > 1 ? "burn" : "burns"} out`);
  if (d.regrown.length) parts.push(`${fields(d.regrown)} grow${d.regrown.length > 1 ? "" : "s"} back`);
  return parts.length ? parts.join(" · ") : "A quiet day.";
}

// ---- beliefs -----------------------------------------------------------------------------------

/** Statuses that mean the agent no longer acts on the belief. */
const DROPPED = new Set(["stale", "retracted", "superseded"]);

/** A belief's status at the end of `day`. Exposures date their changes; any other change (such as
 * an agent retracting a belief itself) is only known as the final status, shown on the last day. */
export function statusAt(run: RunView, b: BeliefView, day: number): string {
  const dated = b.history.filter(([d]) => d <= day);
  if (dated.length) return dated[dated.length - 1]![1];
  if (b.history.length === 0 && b.status !== "active" && day >= lastDay(run)) return b.status;
  return "active";
}

export const isDropped = (status: string) => DROPPED.has(status);

/** The day a belief was dropped, if it was by `day`. */
export function droppedOn(run: RunView, b: BeliefView, day: number): number | null {
  for (let d = b.born; d <= day; d++) if (isDropped(statusAt(run, b, d))) return d;
  return null;
}

/** The agent's beliefs that exist at the end of `day`: live ones first, then by when they formed. */
export function beliefsAt(run: RunView, agent: number, day: number): BeliefView[] {
  const live = (b: BeliefView) => (isDropped(statusAt(run, b, day)) ? 0 : 1);
  return (run.beliefs[String(agent)] ?? [])
    .filter((b) => b.born <= day)
    .sort((p, q) => live(q) - live(p) || p.born - q.born || p.field - q.field);
}

export function findBelief(run: RunView, agent: number, id: string): BeliefView | undefined {
  return (run.beliefs[String(agent)] ?? []).find((b) => b.id === id);
}

/** Whether a supporting route had been cut by `day`, and by which exposures. */
export const routeCuts = (b: BeliefView, route: number[], day: number) =>
  b.cuts.filter((c) => c.day <= day && route.includes(c.agent));

export function originText(b: BeliefView): string {
  if (b.origin === "observed") return "seen directly";
  if (b.origin === "derived") return b.sources.length ? `from ${b.sources.join(", ")}` : "worked out";
  const tellers = [...new Set(b.routes.map((r) => r[r.length - 1]).filter((a) => a !== undefined))];
  return tellers.length ? `told by ${tellers.map(A).join(", ")}` : "told";
}

/** Where the page opens: the first belief an exposure dropped, in the first run that has beliefs,
 * on the day it was dropped. That is the moment the graph's work is easiest to see. */
export function opening(data: CascadeData): { run: string; day: number; agent: number | null; belief: string | null } {
  const labels = Object.keys(data.runs);
  for (const label of labels) {
    const run = data.runs[label]!;
    let best: { day: number; agent: number; belief: string; routes: number } | null = null;
    for (const [agent, beliefs] of Object.entries(run.beliefs))
      for (const b of beliefs) {
        const stale = b.history.find(([, s]) => isDropped(s));
        if (!stale || b.origin !== "told") continue;
        const better = !best || stale[0] < best.day || (stale[0] === best.day && b.routes.length > best.routes);
        if (better) best = { day: stale[0], agent: Number(agent), belief: b.id, routes: b.routes.length };
      }
    if (best) return { run: label, day: best.day, agent: best.agent, belief: best.belief };
  }
  return { run: labels[0] ?? "", day: 0, agent: null, belief: null };
}
