import { describe, expect, it } from "vitest";
import { layout } from "../layout";
import type { BeliefView, RunEvent, TeamSpec, Why } from "../types";
import { caption, distrustAt, nextTick, quarantinedBy, statusAt, tickStats, trailOf } from "./model";

const belief: BeliefView = {
  id: "B7", subject: "trip-tokyo", predicate: "plan.cab_pickup", value: "Thu 15:10", text: "", origin: "told",
  status: "retracted", born: 1, routes: [["travel"]], sources: [],
  history: [{ tick: 4, status: "suspect", reason: "basis changed" }, { tick: 5, status: "retracted", reason: "withdrawn" }],
};

describe("a belief over time", () => {
  it("does not exist before it was made, then follows its changes", () => {
    expect(statusAt(belief, 0)).toBeNull();
    expect(statusAt(belief, 3)).toBe("active");
    expect(statusAt(belief, 4)).toBe("suspect");
    expect(statusAt(belief, 9)).toBe("retracted");
  });
});

it("knows who had quarantined a sender by each tick", () => {
  const events: RunEvent[] = [
    { seq: 1, tick: 5, kind: "exposure", viewer: "travel", agent: "scam" },
    { seq: 2, tick: 5, kind: "exposure", viewer: "inbox", agent: "scam" },
    { seq: 3, tick: 6, kind: "exposure", viewer: "money", agent: "bank-scam" },
  ];
  expect(quarantinedBy(events, 4).size).toBe(0);
  expect([...quarantinedBy(events, 5).get("scam")!]).toEqual(["travel", "inbox"]);
  expect(quarantinedBy(events, 6).has("bank-scam")).toBe(true);
});

it("lays out a team: given positions kept, the rest in columns, Ring Fire on a ring", () => {
  const team: TeamSpec = {
    name: "t", links: [],
    nodes: [
      { id: "mail", type: "stream" }, { id: "router", type: "router" }, { id: "a", type: "agent" },
      { id: "b", type: "agent", position: [10, 20] }, { id: "act", type: "responder" },
    ],
  };
  const at = layout(team);
  expect(at.b).toEqual([10, 20]);
  expect(at.mail![0]).toBeLessThan(at.router![0]);
  expect(at.router![0]).toBeLessThan(at.a![0]);
  const ring = layout({ name: "r", settings: { extra: { layout: "ring" } }, links: [], nodes: [0, 1, 2, 3].map((i) => ({ id: `A${i}`, type: "agent" })) });
  const xs = Object.values(ring).map((p) => Math.round(p[0]));
  expect(new Set(xs).size).toBeGreaterThan(1);
});


const ev = (seq: number, tick: number, kind: string, rest: Record<string, unknown> = {}): RunEvent => ({ seq, tick, kind, ...rest });

describe("a tick in words and numbers", () => {
  const events: RunEvent[] = [
    ev(1, 0, "item", { source: "airline", to: ["travel"] }),
    ev(2, 0, "turn", { node: "travel" }),
    ev(3, 1, "message", { sender: "travel", receiver: "actions", believed: true }),
    ev(4, 1, "message", { sender: "inbox", receiver: "actions", believed: false }),
    ev(5, 2, "change", { viewer: "actions", belief: "B7", new: "retracted", reason: "travel withdrew B5, which this came from: SK101 now Fri" }),
    ev(6, 2, "held", { id: "P1", reason: "travel withdrew B5, which this came from: SK101 now Fri" }),
    ev(7, 3, "exposure", { viewer: "travel", agent: "scam", reason: "said 49 due; checked: 0 due" }),
    ev(8, 3, "exposure", { viewer: "inbox", agent: "scam", reason: "quarantined by travel: said 49 due" }),
  ];

  it("counts what happened", () => {
    expect(tickStats(events, 1)).toMatchObject({ told: 1, bad: 1 });
    expect(tickStats(events, 2)).toMatchObject({ changes: 1, held: 1 });
  });

  it("writes the caption from the most important event", () => {
    expect(caption(events, 0)).toBe("1 item in · 1 turn");
    expect(caption(events, 2)).toBe("1 action held: SK101 now Fri");
    expect(caption(events, 3)).toBe("travel catches scam: said 49 due; checked: 0 due · 2 nodes stop trusting it");
    expect(caption(events, 9)).toBe("Nothing happened.");
  });

  it("jumps to the next tick where something happens", () => {
    expect(nextTick(events, 0, 3, (e) => e.kind === "held")).toBe(2);
    expect(nextTick(events, 2, 3, (e) => e.kind === "held")).toBeNull();
  });

  it("draws an open belief's trail along its routes and copies", () => {
    const why = {
      viewer: "actions",
      belief: { ...belief, id: "B7", born: 1 },
      upstream: [{ observation: "O3", kind: "message", sender: "travel", tick: 1, route: ["airline", "travel"], item: null, source_belief: "B5" }],
      downstream: [{ node: "calendar", belief: "B9", status: "retracted" }],
      derived_from: [], dependents: [], cut_by_distrust: ["airline"], changes: [], actions: [], cypher: {}, live: {}, store: "MemoryStore",
    } as unknown as Why;
    expect(trailOf(why, 0)).toEqual([]); // not born yet
    expect(trailOf(why, 2)).toEqual([
      { from: "airline", to: "travel", cut: true },
      { from: "travel", to: "actions", cut: false },
      { from: "actions", to: "calendar", cut: true },
    ]);
  });
});

it("stops counting a distrust once it was taken back", () => {
  const events: RunEvent[] = [
    { seq: 1, tick: 2, kind: "exposure", viewer: "A5", agent: "A4" },
    { seq: 2, tick: 2, kind: "exposure", viewer: "A5", agent: "A3" },
    { seq: 3, tick: 4, kind: "reinstatement", viewer: "A5", agent: "A4" },
  ];
  expect(distrustAt(events, 3).map((c) => c.agent)).toEqual(["A4", "A3"]);
  expect(distrustAt(events, 4).map((c) => c.agent)).toEqual(["A3"]);
});
