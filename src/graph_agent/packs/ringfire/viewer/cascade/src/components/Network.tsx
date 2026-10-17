import { useLayoutEffect, useRef, useState } from "react";
import type { Selection } from "../App";
import { A, beliefsAt, isImposter, liesPassedOn, routeCuts } from "../model";
import type { RunView, ScenarioView } from "../types";
import { AgentCard } from "./AgentCard";
import { c } from "./css";

interface Props {
  scenario: ScenarioView;
  run: RunView;
  label: string;
  day: number;
  reveal: boolean;
  sel: Selection;
  onSelect: (agent: number | null, belief?: string | null) => void;
  memoryNote: string | null; // shown in the card when the run keeps no belief graph
}

const CX = 300;
const CY = 300;

export function geometry(n: number) {
  const dense = n > 24;
  const R = dense ? 246 : 228;
  const pos = (i: number): [number, number] => {
    const a = (i / n) * 2 * Math.PI - Math.PI / 2;
    return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
  };
  return { n, dense, R, r: dense ? 7.5 : 22, pos };
}

/** A curve from a to b, pulled towards the centre by `lift` (0 is a straight line). */
function arc(p: [number, number], q: [number, number], lift: number) {
  const mx = (p[0] + q[0]) / 2;
  const my = (p[1] + q[1]) / 2;
  return `M${p[0]},${p[1]} Q${mx + (CX - mx) * lift},${my + (CY - my) * lift} ${q[0]},${q[1]}`;
}

/** The agents on a ring: who told whom today, trust cuts so far, and the open belief's trail. */
export function Network({ scenario, run, label, day, reveal, sel, onSelect, memoryNote }: Props) {
  const g = geometry(scenario.n_agents);
  const { n, dense, R, r, pos } = g;
  const focus = sel.agent;
  const box = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  const cuts = run.exposures.filter((e) => e.day <= day);
  const cutPairs = [...new Set(cuts.map((e) => [e.viewer, e.distrusted].sort((a, b) => a - b).join("-")))];
  const links = [
    ...scenario.start_links,
    ...run.days.slice(0, day + 1).flatMap((d) => d.links_added),
  ];
  const today = run.messages.filter((m) => m.day === day).sort((a, b) => Number(a.altered) - Number(b.altered));
  const acted = (i: number) => `${i}|${day}` in run.turns;
  const passedOn = liesPassedOn(scenario, run, day).length;
  const trail = focus !== null && sel.belief ? beliefsAt(run, focus, day).find((b) => b.id === sel.belief) : undefined;

  // place the card beside the open agent, on the side away from the ring's edge
  useLayoutEffect(() => {
    if (focus === null || !box.current || !card.current) return setPlace(null);
    const b = box.current.getBoundingClientRect();
    const scale = b.width / 600;
    const [x, y] = pos(focus);
    const w = Math.min(380, b.width - 24);
    const gap = (r + 12) * scale;
    let left = x * scale > b.width / 2 ? x * scale - w - gap : x * scale + gap;
    left = Math.max(12, Math.min(left, b.width - w - 12));
    const top = Math.max(12, Math.min(y * scale - 60, b.height - card.current.offsetHeight - 12));
    setPlace({ left, top });
  }, [focus, day, sel.belief, label, n]);

  return (
    <section className="panel">
      <div className="ph">
        <div>
          <div className="eyebrow">What the agents tell each other</div>
          <h2>Agent network</h2>
        </div>
        <span className="eyebrow">click an agent</span>
      </div>
      <div className="net" ref={box}>
        <svg viewBox="0 0 600 600" role="img" aria-label="Agents and the messages they send" onClick={() => onSelect(null)}>
          <defs>
            {(["lie", "tru"] as const).map((id) => (
              <marker key={id} id={`h-${id}`} viewBox="0 0 10 10" refX={9} refY={5} markerWidth={dense ? 5 : 7} markerHeight={dense ? 5 : 7} orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill={id === "lie" ? "var(--lie)" : "var(--accent)"} />
              </marker>
            ))}
          </defs>
          <circle cx={CX} cy={CY} r={R} fill="none" stroke="var(--line)" strokeWidth={1.5} />
          {links.map(([a, b], k) => (
            <path key={`l${k}`} d={arc(pos(a!), pos(b!), 1)} fill="none" stroke="var(--line)" strokeWidth={1.5} strokeDasharray="3 5" />
          ))}
          {cutPairs.map((p) => {
            const [a, b] = p.split("-").map(Number) as [number, number];
            const [x1, y1] = pos(a);
            const [x2, y2] = pos(b);
            if (b - a === 1 || (a === 0 && b === n - 1)) {
              const mx = (x1 + x2) / 2;
              const my = (y1 + y2) / 2;
              const k = dense ? 4 : 6;
              return (
                <path key={p} d={`M${mx - k},${my - k} L${mx + k},${my + k} M${mx + k},${my - k} L${mx - k},${my + k}`}
                  stroke="var(--stale)" strokeWidth={dense ? 2.2 : 3} strokeLinecap="round" />
              );
            }
            return <line key={p} x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--stale)" strokeWidth={1} strokeDasharray="4 4" opacity={0.6} />;
          })}

          {today.map((m, k) => {
            const mine = focus !== null && (m.sender === focus || m.receiver === focus);
            const strong = !dense || m.altered || mine;
            const [x1, y1] = pos(m.sender);
            const [x2, y2] = pos(m.receiver);
            const len = Math.hypot(x2 - x1, y2 - y1) || 1;
            const ux = (x2 - x1) / len;
            const uy = (y2 - y1) / len;
            const pad = r + 4;
            const sx = x1 + ux * pad, sy = y1 + uy * pad, ex = x2 - ux * (pad + 2), ey = y2 - uy * (pad + 2);
            const pull = dense ? 0.22 : 0.33 + (k % 3) * 0.06;
            const qx = (sx + ex) / 2 + (CX - (sx + ex) / 2) * pull;
            const qy = (sy + ey) / 2 + (CY - (sy + ey) / 2) * pull;
            const d = `M${sx},${sy} Q${qx},${qy} ${ex},${ey}`;
            const colour = m.altered ? "var(--lie)" : "var(--accent)";
            const op = focus !== null && dense && !mine ? (m.altered ? 0.35 : 0.12) : strong ? 1 : 0.3;
            return (
              <g key={`m${k}`}>
                <path d={d} fill="none" stroke={colour} strokeWidth={dense ? (mine ? 2.4 : 1.6) : 2.4} opacity={op}
                  markerEnd={strong ? `url(#h-${m.altered ? "lie" : "tru"})` : undefined} />
                {strong && (!dense || mine || (m.altered && focus === null)) && (
                  <circle className="comet" r={dense ? 3 : 4.5} fill={colour} opacity={op}>
                    <animateMotion dur="1.8s" repeatCount="indefinite" path={d} begin={`${(k % 4) * 0.3}s`} />
                  </circle>
                )}
                {(!dense || mine) && (
                  <text x={qx} y={qy - 4} textAnchor="middle" fontSize={dense ? 9.5 : 11} fontWeight={600} fill={colour}>
                    F{m.field}: day {m.claim_day}
                  </text>
                )}
              </g>
            );
          })}

          {trail && focus !== null && (
            <g className="trail">
              {trail.routes.filter((rt) => rt.length).map((rt, k) => {
                const cut = routeCuts(trail, rt, day).length > 0;
                const hops = [...rt, focus];
                return hops.slice(0, -1).map((h, i) => (
                  <path key={`t${k}-${i}`} d={arc(pos(h), pos(hops[i + 1]!), 0.5)} fill="none"
                    stroke={cut ? "var(--stale)" : "var(--gold)"} strokeWidth={dense ? 3 : 5} strokeLinecap="round"
                    opacity={0.55} strokeDasharray={cut ? "2 7" : undefined} />
                ));
              })}
              {trail.sent.filter((x) => x.day <= day).map((x, k) => (
                <path key={`s${k}`} d={arc(pos(focus), pos(x.to), 0.2)} fill="none" stroke="var(--gold)"
                  strokeWidth={dense ? 3 : 5} strokeLinecap="round" opacity={0.55} />
              ))}
            </g>
          )}

          {Array.from({ length: n }, (_, i) => {
            const [x, y] = pos(i);
            const imp = reveal && isImposter(scenario, i);
            const on = acted(i);
            const a = (i / n) * 2 * Math.PI - Math.PI / 2;
            const first = i * scenario.fields_per_agent;
            const fieldsText = scenario.fields_per_agent > 1 ? `F${first}–F${first + scenario.fields_per_agent - 1}` : `F${first}`;
            const open = () => onSelect(i);
            return (
              <g key={i} className="node" tabIndex={dense ? -1 : 0} role="button" aria-label={`Open ${A(i)}`}
                onClick={(e) => (e.stopPropagation(), open())}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), open())}>
                {dense && <circle cx={x} cy={y} r={14} fill="transparent" />}
                {focus === i && <circle cx={x} cy={y} r={r + 7} fill="none" stroke="var(--ink)" strokeWidth={2} />}
                <circle className="disc" cx={x} cy={y} r={r} fill={on ? "var(--ink)" : "var(--panel)"}
                  stroke={imp ? "var(--lie)" : "var(--ink)"} strokeWidth={imp ? 2.4 : 1.5}
                  strokeDasharray={imp ? (dense ? "2 2" : "4 3") : undefined} />
                <title>{`${A(i)} · owns ${fieldsText}`}</title>
                {!dense ? (
                  <>
                    <text x={x} y={y + 4.5} textAnchor="middle" fontSize={13} fontWeight={600} fill={on ? "var(--panel)" : "var(--ink)"}>
                      {A(i)}
                    </text>
                    <text x={CX + (R + 40) * Math.cos(a)} y={CY + (R + 40) * Math.sin(a) + 3} textAnchor="middle" fontSize={9.5} fill="var(--muted)">
                      {fieldsText.replace("–", "·")}
                    </text>
                  </>
                ) : (
                  (i % 4 === 0 || focus === i || imp) && (
                    <text x={CX + (R + 22) * Math.cos(a)} y={CY + (R + 22) * Math.sin(a) + 3} textAnchor="middle"
                      fontSize={focus === i ? 11 : 9} fontWeight={focus === i ? 700 : 400} fill={focus === i ? "var(--ink)" : "var(--muted)"}>
                      {A(i)}
                    </text>
                  )
                )}
              </g>
            );
          })}
          <text x={CX} y={CY - 6} textAnchor="middle" fontSize={26} fontWeight={600} fill="var(--ink)" style={{ fontFamily: "var(--f-display)" }}>
            Day {day}
          </text>
          <text x={CX} y={CY + 14} textAnchor="middle" fontSize={10.5} fill="var(--muted)">
            {dense ? "labels every 4th agent · hover for names" : "filled = took a turn today"}
          </text>
        </svg>

        <div className="counter">
          <span className="n" style={c(passedOn ? "var(--lie)" : "var(--ok)")}>{passedOn}</span>
          <span className="l">lies passed on by honest agents so far</span>
        </div>

        {focus !== null && (
          <AgentCard
            ref={card}
            style={place ?? { visibility: "hidden" }}
            scenario={scenario}
            run={run}
            label={label}
            agent={focus}
            day={day}
            reveal={reveal}
            belief={sel.belief}
            onBelief={(b) => onSelect(focus, b)}
            onOpen={onSelect}
            onClose={() => onSelect(null)}
            memoryNote={memoryNote}
          />
        )}
      </div>
      <div className="legend">
        <span><i style={c("var(--accent)")} />true report</span>
        <span><i style={c("var(--lie)")} />false report</span>
        <span><i style={c("var(--stale)")} />trust cut</span>
        <span><i className="o" style={c("var(--ink)")} />agent</span>
        <span><i className="o d" style={c("var(--lie)")} />imposter (revealed)</span>
        <span><i style={c("var(--gold)", { height: 5, opacity: 0.7 })} />open belief's trail</span>
      </div>
    </section>
  );
}
