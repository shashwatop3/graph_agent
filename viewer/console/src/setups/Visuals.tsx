import { useEffect, useState } from "react";
import day from "./quakeDay.json";

/** A story one step at a time: a rail of moments, the current one's line, advancing on its own. */
export function StoryStepper({ steps }: { steps: { when: string; what: string; tone?: string }[] }) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(() => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => setI((k) => (k + 1) % steps.length), 4200);
    return () => window.clearTimeout(t);
  }, [i, playing, steps.length]);
  const step = steps[i]!;
  return (
    <div className="ss">
      <ol className="ss-rail">
        {steps.map((s, k) => (
          <li key={k} className={`${s.tone ?? ""} ${k === i ? "on" : ""} ${k < i ? "past" : ""}`}>
            <button onClick={() => { setI(k); setPlaying(false); }} aria-pressed={k === i}>{s.when}</button>
          </li>
        ))}
      </ol>
      <p key={i} className={`ss-now ${step.tone ?? ""}`}>{step.what}</p>
      <button className="linkish ss-play" onClick={() => setPlaying((p) => !p)}>{playing ? "pause" : "play"}</button>
    </div>
  );
}

/** Which quake is each report about? Origin time runs left to right; each report drops onto the
 * quake it was matched to, in the order it reached the desk. */
const QUAKES = [
  { id: "q-2024-04-02T2358", label: "M7.4 main shock", minute: -2 },
  { id: "q-2024-04-03T0011", label: "M6.4", minute: 11.4 },
  { id: "q-2024-04-03T0035", label: "M5.6", minute: 35.6 },
];
const SOURCE_COLOUR: Record<string, string> = { USGS: "var(--accent)", EMSC: "var(--water)", PTWC: "var(--gold)", ATWC: "var(--gold)", GDACS: "var(--ok)" };

export function MatchTimeline() {
  const matched = day.matched as { report: string; quake: string; why: string }[];
  const [shown, setShown] = useState(0);
  useEffect(() => {
    const t = window.setTimeout(() => setShown((k) => (k >= matched.length ? 0 : k + 1)), shown >= matched.length ? 3500 : 900);
    return () => window.clearTimeout(t);
  }, [shown, matched.length]);
  const x = (minute: number) => 50 + ((minute + 5) / 45) * 520;
  const stack: Record<string, number> = {};
  const now = matched[Math.max(0, shown - 1)];
  return (
    <div className="mt">
      <svg viewBox="0 0 620 210" role="img" aria-label="Thirteen reports, each matched to one of three quakes by origin time">
        <line x1={40} x2={590} y1={160} y2={160} className="mt-axis" />
        {[-5, 0, 10, 20, 30, 40].map((m) => (
          <g key={m}>
            <line x1={x(m)} x2={x(m)} y1={156} y2={164} className="mt-axis" />
            <text x={x(m)} y={180} textAnchor="middle" className="mt-tick">{m < 0 ? "23:55" : `00:${String(m).padStart(2, "0")}`}</text>
          </g>
        ))}
        <text x={590} y={198} textAnchor="end" className="mt-tick">origin time, UTC</text>
        {QUAKES.map((q) => (
          <g key={q.id}>
            <line x1={x(q.minute)} x2={x(q.minute)} y1={30} y2={160} className="mt-lane" />
            <circle cx={x(q.minute)} cy={160} r={7} className="mt-quake" />
            <text x={x(q.minute)} y={22} textAnchor="middle" className="mt-label">{q.label}</text>
          </g>
        ))}
        {matched.slice(0, shown).map((m, k) => {
          const quake = QUAKES.find((q) => q.id === m.quake)!;
          const level = (stack[m.quake] = (stack[m.quake] ?? 0) + 1);
          const source = m.report.startsWith("post") ? "post" : m.report.split(" ")[0]!;
          const colour = SOURCE_COLOUR[source] ?? "var(--lie)";
          const left = k % 2 === 0;
          return (
            <g key={m.report} transform={`translate(${x(quake.minute) + (left ? -14 : 14)},${150 - level * 17})`}>
              <g className="mt-drop">
                <circle r={6} fill={colour} />
                <text x={left ? -10 : 10} y={4} textAnchor={left ? "end" : "start"} className="mt-src">{source === "post" ? m.report.match(/\((.*)\)/)?.[1] : source}</text>
              </g>
            </g>
          );
        })}
      </svg>
      <p className="mt-why">{now ? <><b>{now.report}</b> → {now.quake}: {now.why}</> : "Each report arrives with no quake named…"}</p>
    </div>
  );
}
