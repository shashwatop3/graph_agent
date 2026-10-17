import type { NodeKind, NodeSpec, TeamSpec } from "./types";

export const W = 1000; // the canvas's coordinate space; the SVG scales to fit
export const H = 640;
export const R = 24; // a node's disc
export const R_RING = 19; // on a ring of many agents

export type Positions = Record<string, [number, number]>;
export type Kind = NodeKind | "responder";

/** A team whose agents sit on a ring (the pack says so in its settings). */
export const isRing = (team: TeamSpec) => team.settings?.extra?.layout === "ring";
export const isRingAgent = (team: TeamSpec, id: string) => isRing(team) && /^A\d+$/.test(id);

/** Which column a node type sits in when the team file gives it no position. */
function column(node: NodeSpec): number {
  if (node.type === "stream" || node.type === "schedule" || node.type.endsWith(".world")) return 0;
  if (node.type === "router") return 1;
  if (node.type === "checker" || node.type === "warner" || node.type.endsWith(".rerouter")) return 4;
  if (node.type === "responder") return 3;
  return 2;
}

/** Positions for every node: the team file's own where it has them, a tidy layout elsewhere. Ring
 * Fire's agents sit on a ring, like the Fire game's network. `fresh` ignores saved positions. */
export function layout(team: TeamSpec, fresh = false): Positions {
  const out: Positions = {};
  const given = (n: NodeSpec): [number, number] | null =>
    !fresh && n.position ? [n.position[0], n.position[1]] : null;
  if (isRing(team)) {
    const agents = team.nodes.filter((n) => /^A\d+$/.test(n.id));
    const cx = W / 2, cy = H / 2, rx = 360, ry = 250;
    agents.forEach((n, i) => {
      const a = (i / agents.length) * Math.PI * 2 - Math.PI / 2;
      out[n.id] = given(n) ?? [cx + Math.cos(a) * rx, cy + Math.sin(a) * ry];
    });
    team.nodes.filter((n) => !out[n.id]).forEach((n, i, rest) => {
      out[n.id] = given(n) ?? [cx - ((rest.length - 1) * 90) / 2 + i * 90, cy + 60];
    });
    return out;
  }
  const columns: NodeSpec[][] = [[], [], [], [], []];
  for (const node of team.nodes) {
    const at = given(node);
    if (at) out[node.id] = at;
    else columns[column(node)]!.push(node);
  }
  const xs = [260, 420, 610, 810, 810]; // the left edge is kept for outside senders
  columns.forEach((nodes, c) => {
    const gap = Math.min(130, (H - 170) / Math.max(1, nodes.length - 1));
    const mid = c === 3 ? H / 2 - 80 : c === 4 ? H - 100 : H / 2;
    nodes.forEach((node, i) => {
      out[node.id] = [xs[c]!, mid + (i - (nodes.length - 1) / 2) * (c === 4 ? 90 : gap)];
    });
  });
  return out;
}

/** Where outside senders sit: a column down the left edge. */
export function outsidePos(i: number, n: number): [number, number] {
  const gap = Math.min(42, (H - 70) / Math.max(1, n));
  return [82, 36 + i * gap];
}

export const KIND_COLOUR: Record<Kind, string> = {
  source: "var(--water)",
  code: "var(--muted)",
  model: "var(--accent)",
  scripted: "var(--lie)",
  responder: "var(--gold)",
};

export const KIND_LABEL: Record<Kind, string> = {
  source: "stream",
  code: "code",
  model: "model agent",
  scripted: "scripted",
  responder: "responder",
};

export function kindOf(type: string, kinds: Record<string, NodeKind>): Kind {
  if (type === "responder") return "responder";
  return kinds[type] ?? "code";
}

/** What goes inside a node's disc: an agent's id on a ring, else two letters of its label. */
export function abbrev(id: string, label: string): string {
  if (/^A\d+$/.test(id)) return id;
  const words = label.replace(/[^\w\s]/g, " ").split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0]![0]! + words[1]![0]!).toUpperCase();
  return (words[0] ?? id).slice(0, 2).toUpperCase();
}

/** A curve from p to q, pulled towards (cx, cy) by `lift` (0 is a straight line). */
export function arc(p: [number, number], q: [number, number], lift: number, cx = W / 2, cy = H / 2): string {
  const mx = (p[0] + q[0]) / 2;
  const my = (p[1] + q[1]) / 2;
  return `M${p[0]},${p[1]} Q${mx + (cx - mx) * lift},${my + (cy - my) * lift} ${q[0]},${q[1]}`;
}

/** The ends of a line from p to q, stopped short of discs of radius r1 and r2. */
export function trim(
  p: [number, number],
  q: [number, number],
  r1: number,
  r2: number,
): [[number, number], [number, number]] {
  const dx = q[0] - p[0], dy = q[1] - p[1];
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len, uy = dy / len;
  return [[p[0] + ux * r1, p[1] + uy * r1], [q[0] - ux * r2, q[1] - uy * r2]];
}
