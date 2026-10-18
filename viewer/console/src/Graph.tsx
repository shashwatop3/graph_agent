import { useRef, useState } from "react";
import {
  abbrev,
  arc,
  H,
  isRing,
  isRingAgent,
  KIND_COLOUR,
  kindOf,
  outsidePos,
  type Positions,
  R,
  R_RING,
  trim,
  W,
} from "./layout";
import type { LinkKind, NodeKind, TeamSpec } from "./types";

/** What a run adds to the picture at the tick being shown. */
export interface Live {
  active: Set<string>; // took a turn at this tick (filled disc, as in the Fire game)
  waiting: Set<string>; // something is pending for it
  held: Set<string>; // has actions held because what they rested on changed
  messages: { src: string; dst: string; bad: boolean; label: string }[]; // delivered this tick
  items: { src: string; dst: string; n: number }[]; // hops of the items routed this tick:
  // sender -> stream -> router -> each recipient (n: how many items took that hop)
  carried: Set<string>; // streams and routers that passed items on this tick
  links: { src: string; dst: string }[]; // who can talk to whom now
  outside: { id: string; quarantined: boolean; active: boolean }[];
  cuts: { viewer: string; agent: string }[]; // trust cut between two nodes of the team
}

export interface TrailStep {
  from: string; // node id or outside sender
  to: string;
  cut: boolean; // the route through it was cut
}

interface Props {
  team: TeamSpec;
  positions: Positions;
  kinds: Record<string, NodeKind>;
  selected: string | null;
  onSelect: (id: string | null) => void;
  editable?: boolean;
  onMove?: (id: string, at: [number, number]) => void;
  linkFrom?: string | null;
  selectedLink?: number | null;
  onSelectLink?: (index: number | null) => void;
  live?: Live;
  trail?: TrailStep[];
  centre?: string; // a big label in the middle (the tick on a ring)
}

const LINK_STYLE: Record<LinkKind, { colour: string; dash?: string; arrow: boolean }> = {
  feeds: { colour: "var(--water)", dash: "6 5", arrow: true },
  talks_to: { colour: "var(--line)", arrow: false },
  watches: { colour: "var(--gold)", dash: "2 5", arrow: true },
  owns: { colour: "var(--muted)", arrow: false },
};

/** The team as a graph: nodes as discs, links, and in a run who talked to whom this tick, trust
 * cuts, outside senders (struck out once quarantined) and the open belief's gold trail. */
export function Graph(p: Props) {
  const { team, positions, kinds, selected, live, trail } = p;
  const svg = useRef<SVGSVGElement>(null);
  const [drag, setDrag] = useState<{ id: string; dx: number; dy: number } | null>(null);
  const ring = isRing(team);
  const radius = (id: string) => (isRingAgent(team, id) ? R_RING : R);
  const outside = live?.outside ?? [];
  const outsideAt = new Map(outside.map((o, i) => [o.id, outsidePos(i, outside.length)]));
  const at = (id: string): [number, number] => positions[id] ?? outsideAt.get(id) ?? [W / 2, H / 2];
  const rOf = (id: string) => (outsideAt.has(id) && !positions[id] ? 12 : radius(id));

  const toSvg = (event: React.PointerEvent): [number, number] => {
    const box = svg.current!.getBoundingClientRect();
    return [((event.clientX - box.left) / box.width) * W, ((event.clientY - box.top) / box.height) * H];
  };

  const talks = live ? live.links : team.links.filter((l) => l.kind === "talks_to");
  const directed = team.links
    .map((l, i) => ({ l, i }))
    .filter(({ l }) => l.kind === "feeds" || l.kind === "watches");

  return (
    <svg
      ref={svg}
      viewBox={`0 0 ${W} ${H}`}
      className={`graph ${p.editable ? "editable" : ""}`}
      role="img"
      aria-label={`The team: ${team.nodes.length} nodes`}
      onPointerMove={(e) => {
        if (!drag || !p.onMove) return;
        const [x, y] = toSvg(e);
        p.onMove(drag.id, [Math.round(x - drag.dx), Math.round(y - drag.dy)]);
      }}
      onPointerUp={() => setDrag(null)}
      onPointerLeave={() => setDrag(null)}
      onClick={(e) => {
        if (e.target === svg.current) {
          p.onSelect(null);
          p.onSelectLink?.(null);
        }
      }}
    >
      <defs>
        {(["feeds", "watches"] as LinkKind[]).map((k) => (
          <marker key={k} id={`a-${k}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" fill={LINK_STYLE[k].colour} />
          </marker>
        ))}
        {(["tru", "lie", "item"] as const).map((id) => (
          <marker key={id} id={`h-${id}`} viewBox="0 0 10 10" refX="9" refY="5" orient="auto"
            // an item's arrow keeps one size however thick its hop is drawn
            {...(id === "item" ? { markerUnits: "userSpaceOnUse", markerWidth: 12, markerHeight: 12 } : { markerWidth: 7, markerHeight: 7 })}>
            <path d="M0,0 L10,5 L0,10 z" fill={id === "lie" ? "var(--lie)" : id === "item" ? "var(--water)" : "var(--accent)"} />
          </marker>
        ))}
      </defs>

      {ring && <ellipse cx={W / 2} cy={H / 2} rx={360} ry={250} fill="none" stroke="var(--line)" strokeWidth={1.5} />}
      {ring && p.centre && (
        <text x={W / 2} y={H / 2 - 30} textAnchor="middle" className="centre">{p.centre}</text>
      )}

      {/* the outside world: whoever sends items in */}
      {outside.map((o, i) => {
        const [x, y] = outsidePos(i, outside.length);
        return (
          <g key={o.id} className={`outside ${o.quarantined ? "q" : ""} ${o.active ? "on" : ""}`}>
            <title>{o.quarantined ? `${o.id}: quarantined (caught saying something false)` : o.id}</title>
            <rect x={x - 74} y={y - 11} width={148} height={22} rx={11} />
            <text x={x} y={y + 4} textAnchor="middle">{o.id.length > 22 ? o.id.slice(0, 21) + "…" : o.id}</text>
          </g>
        );
      })}

      {talks.map((l) => {
        const [a, b] = trim(at(l.src), at(l.dst), rOf(l.src), rOf(l.dst));
        return <line key={`t-${l.src}-${l.dst}`} className="link talks" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />;
      })}
      {directed.map(({ l, i }) => {
        const style = LINK_STYLE[l.kind];
        const [a, b] = trim(at(l.src), at(l.dst), rOf(l.src) + 2, rOf(l.dst) + 4);
        const on = p.selectedLink === i;
        return (
          <g key={`d-${i}`} className={`link-g ${on ? "on" : ""}`}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={style.colour} strokeDasharray={style.dash}
              strokeWidth={on ? 3 : 1.6} markerEnd={style.arrow ? `url(#a-${l.kind})` : undefined} />
            {p.editable && (
              <line className="hit" x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
                onClick={(e) => { e.stopPropagation(); p.onSelectLink?.(i); }} />
            )}
          </g>
        );
      })}
      {p.editable && talks.map((l) => {
        const i = team.links.findIndex((x) => x.kind === "talks_to" && x.src === l.src && x.dst === l.dst);
        const [a, b] = [at(l.src), at(l.dst)];
        return (
          <line key={`th-${l.src}-${l.dst}`} className={`hit ${p.selectedLink === i ? "on" : ""}`} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]}
            onClick={(e) => { e.stopPropagation(); p.onSelectLink?.(i); }} />
        );
      })}

      {/* trust cuts between two nodes of the team, as in the Fire game: a cross on the link
          between them, or a faint dashed line between two that do not talk */}
      {[...new Set((live?.cuts ?? []).map((c) => [c.viewer, c.agent].sort().join("\u0000")))].map((pair) => {
        const [u, v] = pair.split("\u0000") as [string, string];
        if (!positions[u] || !positions[v]) return null;
        const [x1, y1] = at(u), [x2, y2] = at(v);
        if (!talks.some((l) => (l.src === u && l.dst === v) || (l.src === v && l.dst === u))) {
          return <line key={`c${pair}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--stale)" strokeWidth={1} strokeDasharray="4 4" opacity={0.6} />;
        }
        const mx = (x1 + x2) / 2, my = (y1 + y2) / 2, s = 6;
        return (
          <path key={`c${pair}`} d={`M${mx - s},${my - s} L${mx + s},${my + s} M${mx + s},${my - s} L${mx - s},${my + s}`}
            stroke="var(--stale)" strokeWidth={3} strokeLinecap="round" />
        );
      })}

      {live?.items.map((m, k) => {
        const [a, b] = trim(at(m.src), at(m.dst), 12, rOf(m.dst) + 4);
        const d = arc(a, b, 0.08);
        return (
          <g key={`i${k}`}>
            <title>{`${m.n} item${m.n > 1 ? "s" : ""}: ${m.src} → ${m.dst}`}</title>
            <path d={d} fill="none" stroke="var(--water)" strokeWidth={1.8 + Math.min(m.n - 1, 4) * 0.6} opacity={0.75} markerEnd="url(#h-item)" />
            <circle className="comet" r={3.5} fill="var(--water)">
              <animateMotion dur="1.6s" repeatCount="indefinite" path={d} begin={`${(k % 4) * 0.3}s`} />
            </circle>
          </g>
        );
      })}

      {live?.messages.map((m, k) => {
        const [a, b] = trim(at(m.src), at(m.dst), rOf(m.src) + 3, rOf(m.dst) + 5);
        const lift = 0.18 + (k % 3) * 0.06;
        const d = arc(a, b, lift);
        const colour = m.bad ? "var(--lie)" : "var(--accent)";
        const qx = (a[0] + b[0]) / 2 + (W / 2 - (a[0] + b[0]) / 2) * lift;
        const qy = (a[1] + b[1]) / 2 + (H / 2 - (a[1] + b[1]) / 2) * lift;
        const mine = selected !== null && (m.src === selected || m.dst === selected);
        return (
          <g key={`m${k}`} opacity={selected === null || mine ? 1 : 0.35}>
            <path d={d} fill="none" stroke={colour} strokeWidth={2.4} markerEnd={`url(#h-${m.bad ? "lie" : "tru"})`} />
            <circle className="comet" r={4.5} fill={colour}>
              <animateMotion dur="1.8s" repeatCount="indefinite" path={d} begin={`${(k % 4) * 0.3}s`} />
            </circle>
            {(live.messages.length <= 4 || mine) && (
              <text x={qx} y={qy - 5} textAnchor="middle" className="msg-label" fill={colour}>{m.label}</text>
            )}
          </g>
        );
      })}

      {trail?.map((t, k) => {
        if (!positions[t.from] && !outsideAt.has(t.from)) return null;
        if (!positions[t.to] && !outsideAt.has(t.to)) return null;
        const [a, b] = trim(at(t.from), at(t.to), rOf(t.from), rOf(t.to));
        return (
          <path key={`tr${k}`} className="trail" d={arc(a, b, 0.25)} fill="none"
            stroke={t.cut ? "var(--stale)" : "var(--gold)"} strokeWidth={5} strokeLinecap="round" opacity={0.6}
            strokeDasharray={t.cut ? "2 7" : undefined} />
        );
      })}

      {team.nodes.map((node) => {
        const [x, y] = at(node.id);
        const kind = kindOf(node.type, kinds);
        const colour = KIND_COLOUR[kind];
        const r = radius(node.id);
        const on = live?.active.has(node.id) ?? false;
        const carried = live?.carried.has(node.id) ?? false;
        const label = node.label || node.id;
        const compact = isRingAgent(team, node.id);
        const owns = team.links.filter((l) => l.kind === "owns" && l.src === node.id).map((l) => l.dst.replace("type:", ""));
        const cls = [
          "node",
          selected === node.id ? "sel" : "",
          on ? "active" : "",
          carried ? "carried" : "",
          live?.waiting.has(node.id) ? "waiting" : "",
          live?.held.has(node.id) ? "held" : "",
          p.linkFrom === node.id ? "linking" : "",
          kind === "scripted" ? "liar" : "",
        ].join(" ");
        return (
          <g
            key={node.id}
            className={cls}
            tabIndex={0}
            role="button"
            aria-label={`${label}, ${node.type}`}
            onClick={(e) => { e.stopPropagation(); p.onSelect(node.id); }}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); p.onSelect(node.id); } }}
            onPointerDown={(e) => {
              if (!p.editable || !p.onMove) return;
              const [px, py] = toSvg(e);
              setDrag({ id: node.id, dx: px - x, dy: py - y });
            }}
          >
            <title>{`${label} · ${node.type}${owns.length ? ` · owns ${owns.join(", ")}` : ""}`}</title>
            {selected === node.id && <circle cx={x} cy={y} r={r + 7} fill="none" stroke="var(--ink)" strokeWidth={2} />}
            {carried && <circle cx={x} cy={y} r={r + 4} fill="none" stroke="var(--water)" strokeWidth={2.5} />}
            {live?.held.has(node.id) && <circle cx={x} cy={y} r={r + 4} fill="none" stroke="var(--gold)" strokeWidth={2.5} strokeDasharray="4 3" />}
            <circle className="disc" cx={x} cy={y} r={r} fill={on ? "var(--ink)" : "var(--panel)"}
              stroke={kind === "scripted" ? "var(--lie)" : "var(--ink)"} strokeWidth={1.5}
              strokeDasharray={kind === "scripted" ? "4 3" : undefined} />
            <circle cx={x + r * 0.72} cy={y - r * 0.72} r={5} fill={colour} stroke="var(--panel)" strokeWidth={1.5} />
            <text x={x} y={y + 4.5} textAnchor="middle" className="glyph" fill={on ? "var(--panel)" : "var(--ink)"}>
              {abbrev(node.id, label)}
            </text>
            {!compact && (
              <>
                <text x={x} y={y + r + 15} textAnchor="middle" className="t1">{label.length > 20 ? label.slice(0, 19) + "…" : label}</text>
                <text x={x} y={y + r + 27} textAnchor="middle" className="t2">
                  {node.type}{owns.length ? ` · ${owns.slice(0, 2).join(", ")}${owns.length > 2 ? "…" : ""}` : ""}
                </text>
              </>
            )}
            {on && <circle className="pulse" cx={x - r * 0.72} cy={y - r * 0.72} r={4} />}
          </g>
        );
      })}
    </svg>
  );
}
