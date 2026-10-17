import { describe, expect, it } from "vitest";
import { beliefsAt, caption, droppedOn, liesPassedOn, opening, originText, routeCuts, statusAt, worldAt } from "./model";
import type { BeliefView, CascadeData, RunView, ScenarioView } from "./types";

// Four agents, one field each; A1 is an imposter. A1 lies to A2 about F3 on day 1, A0 passes the
// same lie on through A1. A2 cuts A1 on day 1 and A0 on day 2, so the lie loses both routes.
const scenario: ScenarioView = { seed: 0, n_agents: 4, fields_per_agent: 1, n_fields: 4, imposters: { "1": "false_alarm" }, start_links: [] };

const day = (d: number, more: Partial<RunView["days"][number]> = {}) => ({
  day: d, ignited: [], burnt_out: [], regrown: [], saved: [], watered: [], links_added: [], ...more,
});

const lie: BeliefView = {
  id: "B1", field: 3, value: 9, origin: "told", status: "stale", born: 1, history: [[2, "stale"]],
  routes: [[0, 1], [1]], sources: [], dependents: [], sent: [], became: [], true: false,
  cuts: [{ day: 1, agent: 1, reason: "lied" }, { day: 2, agent: 0, reason: "lied too" }],
};
const seen: BeliefView = { ...lie, id: "B2", value: 3, origin: "observed", status: "active", history: [], routes: [[]], cuts: [], dependents: ["B3"], true: true };
const derived: BeliefView = { ...seen, id: "B3", origin: "derived", routes: [], dependents: [], sources: ["B2"], born: 2 };

const run: RunView = {
  system: "graph-memory", model: "test",
  days: [day(0, { ignited: [0] }), day(1, { burnt_out: [0], ignited: [1] }), day(2, { saved: [2] }), day(3, { regrown: [0] })],
  messages: [
    { day: 1, sender: 1, receiver: 2, route: [1], field: 3, claim_day: 9, altered: true },
    { day: 2, sender: 2, receiver: 3, route: [1, 2], field: 3, claim_day: 9, altered: true },
    { day: 2, sender: 2, receiver: 3, route: [2], field: 3, claim_day: 3, altered: false },
  ],
  exposures: [
    { day: 1, viewer: 2, distrusted: 1, reason: "lied", changed: [] },
    { day: 2, viewer: 2, distrusted: 0, reason: "lied too", changed: ["B1"] },
  ],
  turns: {}, beliefs: { "2": [lie, seen, derived] }, score: {},
};

describe("the world", () => {
  it("follows each field through fire, water and regrowth", () => {
    expect(worldAt(run, 1)).toEqual(new Map([[0, "burnt"], [1, "burning"]]));
    expect(worldAt(run, 2).get(2)).toBe("saved");
    expect(worldAt(run, 3).has(0)).toBe(false); // grew back
  });

  it("counts only lies honest agents passed on, not the imposter's own", () => {
    expect(liesPassedOn(scenario, run, 1)).toHaveLength(0);
    expect(liesPassedOn(scenario, run, 2)).toHaveLength(1);
    expect(caption(scenario, run, 2)).toContain("A2 passes a lie on");
  });
});

describe("a belief over time", () => {
  it("is dropped on the day its last route is cut, not before", () => {
    expect(statusAt(run, lie, 1)).toBe("active");
    expect(routeCuts(lie, [1], 1)).toHaveLength(1);
    expect(routeCuts(lie, [0, 1], 1)).toHaveLength(1); // A1 is on this route too
    expect(droppedOn(run, lie, 1)).toBeNull();
    expect(droppedOn(run, lie, 3)).toBe(2);
  });

  it("only exists from the day it was made, live beliefs listed first", () => {
    expect(beliefsAt(run, 2, 1).map((b) => b.id)).toEqual(["B1", "B2"]);
    expect(beliefsAt(run, 2, 2).map((b) => b.id)).toEqual(["B2", "B3", "B1"]);
  });

  it("says where it came from", () => {
    expect(originText(lie)).toBe("told by A1");
    expect(originText(seen)).toBe("seen directly");
    expect(originText(derived)).toBe("from B2");
  });
});

it("opens on the first belief an exposure dropped", () => {
  const data: CascadeData = { scenario, runs: { chat: { ...run, beliefs: {} }, graph: run } };
  expect(opening(data)).toEqual({ run: "graph", day: 2, agent: 2, belief: "B1" });
  expect(opening({ scenario, runs: { chat: { ...run, beliefs: {} } } })).toEqual({ run: "chat", day: 0, agent: null, belief: null });
});
