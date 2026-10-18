import type { NodeSpec, TeamSpec } from "../types";

/** A team, drawn from its own spec (what will run, not a picture of it). "flow": where items come
 * from, the router, the agents, the one that acts, and the checker under them. "ring": agents on
 * a ring around their world, each line a pair that talks. */
export function TeamDiagram({ team, layout }: { team: TeamSpec; layout: "flow" | "ring" }) {
  return layout === "ring" ? <Ring team={team} /> : <Flow team={team} />;
}

const COLOUR: Record<string, string> = {
  stream: "var(--water)",
  router: "var(--muted)",
  agent: "var(--accent)",
  scripted: "var(--lie)",
  responder: "var(--gold)",
  checker: "var(--ok)",
};
const colourOf = (n: NodeSpec) => COLOUR[n.type] ?? "var(--fire)"; // a pack's world: the fire
const labelOf = (n: NodeSpec) => n.label || n.id;

function Box({ x, y, w, node, sub }: { x: number; y: number; w: number; node: NodeSpec; sub?: string }) {
  const colour = colourOf(node);
  const label = labelOf(node).split(":")[0]!; // "USGS: earthquakes, …" is drawn as USGS
  const short = label.length > 18 ? `${label.slice(0, 17)}…` : label;
  return (
    <g>
      <rect x={x - w / 2} y={y - 17} width={w} height={34} rx={9} fill="var(--panel)" stroke={colour} strokeWidth={1.5} />
      <circle cx={x - w / 2 + 12} cy={y} r={4} fill={colour} />
      <text x={x - w / 2 + 22} y={sub ? y - 2 : y + 4} fontSize={12} fill="var(--ink)">{short}</text>
      {sub && <text x={x - w / 2 + 22} y={y + 11} fontSize={9.5} fill="var(--muted)" fontFamily="var(--f-mono)">{sub}</text>}
    </g>
  );
}

function Flow({ team }: { team: TeamSpec }) {
  const sources = team.nodes.filter((n) => n.type === "stream");
  const router = team.nodes.filter((n) => n.type === "router");
  const agents = team.nodes.filter((n) => n.type === "agent" || n.type === "scripted");
  const doers = team.nodes.filter((n) => n.type === "responder");
  const checker = team.nodes.find((n) => n.type === "checker");
  const columns = [sources, router, agents, doers].filter((c) => c.length > 0);
  const W = 720;
  const rows = Math.max(...columns.map((c) => c.length));
  const H = rows * 52 + 90;
  const colX = columns.map((_, i) => 90 + (i * (W - 180)) / Math.max(1, columns.length - 1));
  const at = new Map<string, [number, number]>();
  columns.forEach((column, i) => {
    const top = (H - 70 - (column.length - 1) * 52) / 2;
    column.forEach((n, k) => at.set(n.id, [colX[i]!, top + k * 52]));
  });
  const edges: [string, string, boolean][] = []; // from, to, dashed
  for (const s of sources) for (const r of router) edges.push([s.id, r.id, false]);
  for (const r of router) for (const a of agents) edges.push([r.id, a.id, true]);
  for (const l of team.links) {
    if ((l.kind === "watches" || l.kind === "talks_to") && doers.some((d) => d.id === l.src || d.id === l.dst)) {
      const [from, to] = doers.some((d) => d.id === l.src) ? [l.dst, l.src] : [l.src, l.dst];
      if (at.has(from) && at.has(to) && !edges.some(([f, t]) => f === from && t === to)) edges.push([from, to, false]);
    }
  }
  return (
    <svg className="team-diagram" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`The ${team.name} team: ${team.nodes.map(labelOf).join(", ")}`}>
      {edges.map(([f, t, dashed], i) => {
        const [x1, y1] = at.get(f)!;
        const [x2, y2] = at.get(t)!;
        const mid = (x1 + x2) / 2;
        return <path key={i} d={`M${x1 + 70},${y1} C${mid},${y1} ${mid},${y2} ${x2 - 70},${y2}`} fill="none" stroke="var(--line)" strokeWidth={1.4} strokeDasharray={dashed ? "4 4" : undefined} />;
      })}
      {[...at.entries()].map(([id, [x, y]]) => {
        const node = team.nodes.find((n) => n.id === id)!;
        return <Box key={id} x={x} y={y} w={140} node={node} sub={node.type === "responder" ? "acts" : undefined} />;
      })}
      {checker && (
        <g>
          <line x1={60} x2={W - 60} y1={H - 52} y2={H - 52} stroke="var(--ok)" strokeDasharray="2 5" strokeWidth={1.2} />
          <Box x={W / 2} y={H - 26} w={190} node={checker} sub="checks what was told" />
        </g>
      )}
    </svg>
  );
}

function Ring({ team }: { team: TeamSpec }) {
  const keepers = team.nodes.filter((n) => n.type === "agent" || n.type === "scripted");
  const world = team.nodes.find((n) => n.type !== "agent" && n.type !== "scripted" && n.type !== "checker");
  const checker = team.nodes.find((n) => n.type === "checker");
  const W = 520;
  const H = 440;
  const cx = W / 2;
  const cy = 200;
  const R = 150;
  const at = new Map(keepers.map((n, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / keepers.length;
    return [n.id, [cx + R * Math.cos(angle), cy + R * Math.sin(angle)] as [number, number]];
  }));
  const pairs = new Set<string>();
  for (const l of team.links) {
    if (l.kind === "talks_to" && at.has(l.src) && at.has(l.dst)) pairs.add([l.src, l.dst].sort().join("|"));
  }
  return (
    <svg className="team-diagram" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${keepers.length} keepers on a ring around the fire world`}>
      <circle cx={cx} cy={cy} r={R} fill="none" stroke="var(--line)" strokeDasharray="3 6" />
      {[...pairs].map((p) => {
        const [a, b] = p.split("|");
        const [x1, y1] = at.get(a!)!;
        const [x2, y2] = at.get(b!)!;
        return <line key={p} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--line)" strokeWidth={1.4} />;
      })}
      {world && (
        <g>
          <circle cx={cx} cy={cy} r={46} fill="color-mix(in srgb, var(--fire) 14%, transparent)" stroke="var(--fire)" strokeWidth={1.5} />
          <path d={`M${cx},${cy - 22} C${cx + 16},${cy - 4} ${cx + 12},${cy + 14} ${cx},${cy + 18} C${cx - 12},${cy + 14} ${cx - 16},${cy - 4} ${cx},${cy - 22} Z`} fill="var(--fire)" opacity={0.85} />
          <text x={cx} y={cy + 66} textAnchor="middle" fontSize={11} fill="var(--muted)">{labelOf(world)}</text>
        </g>
      )}
      {keepers.map((n) => {
        const [x, y] = at.get(n.id)!;
        const liar = n.type === "scripted";
        return (
          <g key={n.id}>
            <circle cx={x} cy={y} r={22} fill="var(--panel)" stroke={liar ? "var(--lie)" : "var(--accent)"} strokeWidth={liar ? 2.2 : 1.5} />
            <text x={x} y={y + 4} textAnchor="middle" fontSize={12} fontFamily="var(--f-mono)" fill={liar ? "var(--lie)" : "var(--ink)"}>{n.id}</text>
            {liar && <text x={x} y={y + 36} textAnchor="middle" fontSize={9.5} fill="var(--lie)">liar</text>}
          </g>
        );
      })}
      {checker && <Box x={cx} y={H - 30} w={210} node={checker} sub="refutes, blames the first hop" />}
    </svg>
  );
}
