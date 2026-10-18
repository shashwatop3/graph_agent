import { useEffect, useMemo, useState } from "react";
import data from "./fireDays.json";

/** The first days of the free stand-in game (fireDays.json, made by packs/ringfire/snapshot.py),
 * played on the ring: fire strength per field, water, every warning travelling its link (magenta:
 * the liars' claim), the liars cut off once caught, keepers offline, the hidden path once used. */

interface Day {
  day: number;
  strength: Record<string, number>;
  watered: number[];
  put_out: number[];
  sends: { from: string; to: string; lie: boolean; believed: boolean }[];
  caught: [string, string][];
  offline: string[];
  links: number[][];
}
const GAME = data as unknown as { agents: number; liars: string[]; days: Day[] };

export const FIRE_CAPTIONS = [
  "Fire starts at F0. A0 waters it and warns its neighbours.",
  "The liars claim fire reaches F4 tomorrow. Honest neighbours pass it on.",
  "No fire at F4: the claim is refuted. Every keeper cuts the liars, not the relays.",
  "A3 goes offline, so F3 burns unwatered.",
  "Fire jumps F3 → F1 along a hidden path.",
  "Honest keepers water as fire arrives. The liars let theirs burn.",
  "The liar's F2 reaches 5. Warnings still route around it.",
  "Keepers put fires out the day they arrive.",
  "A3 goes offline again; its neighbours keep warning.",
  "Day 9: no liar is believed; no water is wasted.",
];

const N = GAME.agents;
const CX = 200, CY = 190, R = 140;
const at = (i: number): [number, number] => {
  const a = -Math.PI / 2 + (i * 2 * Math.PI) / N;
  return [CX + R * Math.cos(a), CY + R * Math.sin(a)];
};
const num = (id: string) => Number(id.slice(1));

export function FirePlayback() {
  const last = GAME.days.length - 1;
  const [day, setDay] = useState(0);
  const [playing, setPlaying] = useState(() => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => setDay((d) => (d >= last ? 0 : d + 1)), day >= last ? 4200 : 3200);
    return () => window.clearTimeout(t);
  }, [day, playing, last]);

  const d = GAME.days[day]!;
  // cut links: a keeper that caught a liar stops listening to it, from that day on
  const cut = useMemo(() => {
    const found = new Set<string>();
    for (const x of GAME.days.slice(0, day + 1)) for (const [v, a] of x.caught) found.add([v, a].sort().join("|"));
    return found;
  }, [day]);
  const hidden = day >= 4;

  return (
    <figure className="fp">
      <svg viewBox="0 0 400 380" role="img" aria-label={`Ring Fire, day ${day}: ${FIRE_CAPTIONS[day]}`}>
        <defs>
          <radialGradient id="fp-fire"><stop offset="0%" stopColor="#ffd166" /><stop offset="60%" stopColor="var(--fire)" /><stop offset="100%" stopColor="var(--fire)" stopOpacity="0" /></radialGradient>
        </defs>
        {/* links: who can talk to whom */}
        {d.links.map(([a, b]) => {
          const [x1, y1] = at(a!), [x2, y2] = at(b!);
          const isCut = cut.has([`A${a}`, `A${b}`].sort().join("|"));
          return <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} className={`fp-link ${isCut ? "cut" : ""}`} />;
        })}
        {hidden && (() => {
          const [x1, y1] = at(3), [x2, y2] = at(1);
          return <path d={`M${x1},${y1} Q${CX - 30},${CY - 20} ${x2},${y2}`} className="fp-hidden" />;
        })()}
        {/* warnings in flight: restart every day */}
        <g key={`sends-${day}`}>
          {d.sends.map((s, i) => {
            const [x1, y1] = at(num(s.from)), [x2, y2] = at(num(s.to));
            const path = `M${x1},${y1} L${x2},${y2}`;
            return (
              <circle key={i} r={s.lie ? 5 : 3.6} className={`fp-msg ${s.lie ? "lie" : ""} ${s.believed ? "" : "dropped"}`}>
                <animateMotion dur="1.4s" begin={`${(i % 6) * 0.12}s`} fill="freeze" path={path} />
              </circle>
            );
          })}
        </g>
        {/* fields and keepers */}
        {Array.from({ length: N }, (_, i) => {
          const [x, y] = at(i);
          const strength = d.strength[String(i)] ?? 0;
          const liar = GAME.liars.includes(`A${i}`);
          const off = d.offline.includes(`A${i}`);
          const watered = d.watered.includes(i);
          const out = d.put_out.includes(i);
          return (
            <g key={i} transform={`translate(${x},${y})`} className={`fp-field ${liar ? "liar" : ""} ${off ? "off" : ""}`}>
              <circle r={25} className="fp-disc" />
              {strength > 0 && <circle r={8 + strength * 4} fill="url(#fp-fire)" className="fp-flame" />}
              <text y={-2} textAnchor="middle" className="fp-name">F{i}</text>
              <text y={11} textAnchor="middle" className="fp-keeper">{off ? "offline" : liar ? `A${i} liar` : `A${i}`}</text>
              {strength > 0 && <text x={22} y={-20} className="fp-str">{strength}</text>}
              {watered && <path key={`w${day}`} d="M0,-46 C5,-38 6,-34 0,-30 C-6,-34 -5,-38 0,-46 Z" className="fp-drop" />}
              {out && <text key={`o${day}`} y={44} textAnchor="middle" className="fp-out">put out</text>}
            </g>
          );
        })}
        <text x={CX} y={CY - 6} textAnchor="middle" className="fp-day">Day {day}</text>
        <text x={CX} y={CY + 14} textAnchor="middle" className="fp-sub">{d.sends.length} warnings</text>
      </svg>
      <figcaption>
        <p key={day} className="fp-caption">{FIRE_CAPTIONS[day]}</p>
        <div className="fp-controls">
          <button className="btn" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
          {GAME.days.map((x) => (
            <button key={x.day} className={`l-dot ${x.day === day ? "on" : ""}`} aria-label={`Day ${x.day}`} aria-pressed={x.day === day} onClick={() => { setDay(x.day); setPlaying(false); }} />
          ))}
        </div>
        <div className="fp-key">
          <span><i className="k-fire" />fire</span>
          <span><i className="k-msg" />warning</span>
          <span><i className="k-lie" />the lie</span>
          <span><i className="k-cut" />cut off</span>
          <span><i className="k-drop" />watered</span>
        </div>
      </figcaption>
    </figure>
  );
}
