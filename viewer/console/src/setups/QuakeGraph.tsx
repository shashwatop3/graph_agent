import { useEffect, useMemo, useRef, useState } from "react";
import day from "./quakeDay.json";

/** The Hualien day's graph as one free stand-in run left it, minute by minute (quakeDay.json, made
 * by packs/hualien/snapshot.py). Columns: who reported, the reports, the facts they support, what
 * was planned from those, and what ops did. A band per quake, and one for the fabs. Hover a node
 * to light up what it rests on and what rests on it. */

interface GNode {
  id: string;
  kind: "source" | "report" | "fact" | "plan" | "action";
  group: string;
  label: string;
  born: number;
  status?: [number, string][];
  post?: boolean;
  rumour?: boolean;
  text?: string;
  owner?: string;
  origin?: string;
  source?: string;
}
interface GEdge { src: string; dst: string; kind: string }

const DATA = day as unknown as { ticks: string[]; groups: string[]; nodes: GNode[]; edges: GEdge[] };
const COLUMN: Record<GNode["kind"], number> = { source: 70, report: 250, fact: 470, plan: 680, action: 890 };
const WIDTH: Record<GNode["kind"], number> = { source: 120, report: 196, fact: 150, plan: 196, action: 150 };
const HEAD: Record<GNode["kind"], string> = { source: "Who reported", report: "Reports", fact: "Facts", plan: "Planned", action: "Done" };
const ROW = 30;
const BAND_GAP = 26;
const TOP = 46;
const BANDS: Record<string, string> = {
  "q-2024-04-02T2358": "Main shock · 23:58 UTC",
  "q-2024-04-03T0011": "Aftershock · 00:11",
  "q-2024-04-03T0035": "Aftershock · 00:35",
  fabs: "The fabs",
  none: "About no quake",
};

function statusAt(n: GNode, tick: number): string {
  let now = n.kind === "action" ? "done" : "active";
  for (const [t, s] of n.status ?? []) if (t <= tick) now = s;
  return now;
}

function layout() {
  const at = new Map<string, [number, number]>();
  const bands: { group: string; top: number; bottom: number }[] = [];
  let y = TOP;
  for (const group of DATA.groups) {
    const inBand = DATA.nodes.filter((n) => n.group === group && n.kind !== "source");
    if (!inBand.length) continue;
    const top = y;
    let rows = 0;
    for (const kind of ["report", "fact", "plan", "action"] as const) {
      const col = inBand.filter((n) => n.kind === kind).sort((a, b) => a.born - b.born || a.id.localeCompare(b.id, undefined, { numeric: true }));
      col.forEach((n, i) => at.set(n.id, [COLUMN[kind], top + 30 + i * ROW]));
      rows = Math.max(rows, col.length);
    }
    y = top + 30 + rows * ROW + BAND_GAP;
    bands.push({ group, top: top - 4, bottom: y - BAND_GAP + 4 });
  }
  // a source sits level with the middle of its reports, then sources are spread so none overlap
  const sources = DATA.nodes.filter((n) => n.kind === "source").map((n) => {
    const ys = DATA.edges.filter((e) => e.src === n.id).map((e) => at.get(e.dst)?.[1]).filter((v): v is number => v !== undefined);
    return { n, y: ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : TOP };
  }).sort((a, b) => a.y - b.y);
  let last = -Infinity;
  for (const s of sources) {
    const placed = Math.max(s.y, last + ROW);
    at.set(s.n.id, [COLUMN.source, placed]);
    last = placed;
  }
  return { at, bands, height: Math.max(y, last + ROW) + 8 };
}

export function QuakeGraph({ captions }: { captions?: string[] }) {
  const { at, bands, height } = useMemo(layout, []);
  const last = DATA.ticks.length - 1;
  // with captions it tells the story from the start, playing once it is scrolled into view
  const [tick, setTick] = useState(captions ? 0 : last);
  const [playing, setPlaying] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!captions || !box.current || window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const seen = new IntersectionObserver(([entry]) => {
      if (entry?.isIntersecting) { setPlaying(true); seen.disconnect(); }
    }, { threshold: 0.35 });
    seen.observe(box.current);
    return () => seen.disconnect();
  }, [captions]);
  const [hover, setHover] = useState<string | null>(null);
  useEffect(() => {
    if (!playing) return;
    if (tick >= last) { setPlaying(false); return; }
    const t = window.setTimeout(() => setTick((k) => k + 1), captions ? 3200 : 1400);
    return () => window.clearTimeout(t);
  }, [playing, tick, last, captions]);

  const lit = useMemo(() => {
    if (!hover) return null;
    const found = new Set([hover]);
    const walk = (from: string, up: boolean) => {
      for (const e of DATA.edges) {
        const [a, b] = up ? [e.dst, e.src] : [e.src, e.dst];
        if (a === from && !found.has(b)) { found.add(b); walk(b, up); }
      }
    };
    walk(hover, true);
    walk(hover, false);
    return found;
  }, [hover]);

  const visible = (n: GNode) => n.born <= tick;
  const byId = new Map(DATA.nodes.map((n) => [n.id, n]));
  const hovered = hover ? byId.get(hover) : undefined;
  return (
    <div className="qg" ref={box}>
      {captions && <p key={tick} className="qg-caption">{captions[tick]}</p>}
      <div className="qg-bar">
        <button className="btn" onClick={() => { if (tick >= last) setTick(0); setPlaying((p) => !p); }} aria-label={playing ? "Pause" : "Play the replay"}>{playing ? "❚❚" : "▶"}</button>
        <input type="range" min={0} max={last} value={tick} onChange={(e) => { setTick(Number(e.target.value)); setPlaying(false); }} aria-label="Time in the replay" />
        <b className="qg-time">{DATA.ticks[tick]}</b>
        <span className="qg-key">
          <span><i className="k-active" />active</span>
          <span><i className="k-suspect" />suspect / held</span>
          <span><i className="k-gone" />retracted / stale</span>
          <span><i className="k-post" />a post</span>
        </span>
      </div>
      <div className="qg-scroll">
        <svg viewBox={`0 0 980 ${height}`} style={{ minWidth: 820 }} role="img" aria-label="The replay's graph: sources, reports, facts, plans and actions for three quakes and three fabs">
          {(Object.keys(HEAD) as GNode["kind"][]).map((k) => (
            <text key={k} x={COLUMN[k]} y={20} textAnchor="middle" className="qg-head">{HEAD[k].toUpperCase()}</text>
          ))}
          {bands.map((b) => (
            <g key={b.group}>
              <rect x={150} y={b.top} width={826} height={b.bottom - b.top} rx={10} className="qg-band" />
              <text x={160} y={b.top + 12} className="qg-bandlabel">{BANDS[b.group] ?? b.group}{b.group.startsWith("q-") ? ` · ${b.group}` : ""}</text>
            </g>
          ))}
          {DATA.edges.map((e, i) => {
            const a = byId.get(e.src), b = byId.get(e.dst);
            if (!a || !b || !visible(a) || !visible(b)) return null;
            const [x1, y1] = at.get(e.src)!, [x2, y2] = at.get(e.dst)!;
            const sx = x1 + WIDTH[a.kind] / 2, tx = x2 - WIDTH[b.kind] / 2;
            const on = lit ? lit.has(e.src) && lit.has(e.dst) : false;
            const gone = ["retracted", "stale"].includes(statusAt(a, tick)) && a.kind !== "source" && a.kind !== "report";
            return <path key={i} d={`M${sx},${y1} C${sx + 40},${y1} ${tx - 40},${y2} ${tx},${y2}`} className={`qg-edge ${e.kind} ${on ? "on" : ""} ${lit && !on ? "dim" : ""} ${gone ? "gone" : ""}`} />;
          })}
          {DATA.nodes.filter(visible).map((n) => {
            const [x, y] = at.get(n.id)!;
            const w = WIDTH[n.kind];
            const status = statusAt(n, tick);
            const max = Math.floor(w / 6.6);
            const label = n.label.length > max ? `${n.label.slice(0, max - 1)}…` : n.label;
            const fresh = n.born === tick || (n.status ?? []).some(([t]) => t === tick && t > n.born);
            return (
              <g key={n.id} transform={`translate(${x - w / 2},${y - 11})`} className={`qg-node ${n.kind} s-${status} ${n.post ? "post" : ""} ${n.rumour ? "rumour" : ""} ${lit && !lit.has(n.id) ? "dim" : ""} ${fresh ? "fresh" : ""}`}
                onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)} onFocus={() => setHover(n.id)} onBlur={() => setHover(null)} tabIndex={0}>
                <rect width={w} height={22} rx={n.kind === "report" ? 11 : n.kind === "action" ? 3 : 6} />
                <text x={8} y={15}>{label}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="qg-detail" aria-live="polite">
        {hovered
          ? <>{describe(hovered, tick)}</>
          : <>Hover a node: what it rests on, and what rests on it, light up.</>}
      </p>
    </div>
  );
}

function describe(n: GNode, tick: number): string {
  const status = statusAt(n, tick);
  if (n.kind === "source") return `${n.label}: ${n.post ? "an account that posts (written for the replay)" : n.label === "FabA's sensors" ? "a checking tool: what it reads is evidence" : "an agency"}.`;
  if (n.kind === "report") return `${n.source}: “${n.text}”${n.post ? " (a post written for the replay)" : ""}`;
  const whose = n.owner ? ` · held by ${n.owner}` : "";
  const how = n.origin === "observed" ? " · evidence" : n.kind === "fact" ? " · told" : "";
  return `${n.id} ${n.label}${whose}${how} · ${status} at ${DATA.ticks[tick]}`;
}
