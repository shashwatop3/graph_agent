import { useState } from "react";
import { c } from "../css";
import "../landing/landing.css";
import type { Guide } from "./guide";
import { QuakeGraph } from "./QuakeGraph";
import day from "./quakeDay.json";

/** A setup's long explainer (guide.ts): the game, a day, what an agent reads, its tools, how each
 * kind of node decides, and a real run. */
export function GuideView({ guide }: { guide: Guide }) {
  const [tab, setTab] = useState(0);
  const section = guide.screen.sections[tab]!;
  const t = guide.titles ?? {};
  const quake = guide.visual === "quake";
  return (
    <>
      <section className="panel">
        <div className="ph"><div><div className="eyebrow">{quake ? "Real records, replayed" : "First, the game"}</div><h2>{t.game ?? "How it works"}</h2></div></div>
        {quake
          ? <div className="pb"><p className="g-lead">{guide.game}</p></div>
          : (
            <div className="pb g-game">
              <div>
                <p className="g-lead">{guide.game}</p>
                <FireTrack />
              </div>
              <RingBoard />
            </div>
          )}
        <div className="pb g-rules">
          {guide.rules.map((r) => <div key={r.title}><h3>{r.title}</h3><p>{r.body}</p></div>)}
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">{quake ? "What the desks are for" : "What everyone is playing for"}</div><h2>{quake ? "Goal and checks" : "Goal and score"}</h2></div></div>
        <div className="pb">
          <p className="g-lead">{guide.goal}</p>
          <ul className="g-score">{guide.score.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">{t.dayEyebrow ?? "Every day, in this order"}</div><h2>{t.day ?? "One day of the game"}</h2></div></div>
        <div className="pb">
          <ol className="g-day">
            {guide.day.map((d) => <li key={d.when}><b>{d.when}</b><p>{d.what}</p></li>)}
          </ol>
        </div>
      </section>

      {quake && (
        <>
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">The edge case: which quake is this?</div><h2>Every report, matched</h2></div></div>
            <div className="pb">
              <p className="g-lead">No report says which quake it is about, and the three quakes are in the same region on the same day. Matching by region and date, as the live desk first did, makes them one quake: the aftershock's M6.4 then overwrites the main shock's 7.4, and on the live desk, where the agencies' figures are evidence, an honest poster who reported the aftershock is blamed for lying. Matching by origin time and distance keeps them apart:</p>
              <table className="g-match">
                <thead><tr><th>Report</th><th>Quake</th><th>Why</th></tr></thead>
                <tbody>
                  {(day.matched as { report: string; quake: string; why: string }[]).map((m) => (
                    <tr key={m.report} className={m.why.startsWith("a new quake") || m.why.startsWith("the first") ? "new" : ""}>
                      <td>{m.report}</td><td>{m.quake}</td><td className="why">{m.why}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">From one free replay, not a mock-up</div><h2>The graph, minute by minute</h2></div></div>
            <div className="pb">
              <p className="g-lead">Every report, the facts it supports, the bulletins and fab ratings planned from them, and what ops did. Press play: at 00:15 a lie is caught by a fab's own sensors; at 00:40 the review reaches along DERIVED_FROM to exactly the main shock's bulletin and the fab alerts, while the aftershocks' stay green.</p>
              <QuakeGraph />
            </div>
          </section>
        </>
      )}

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Each turn, compiled from the graph</div><h2>{t.screen ?? "What a keeper reads"}</h2></div></div>
        <div className="pb">
          <p className="note g-top">{guide.screen.who}</p>
          <div className="g-screen">
            <div className="g-tabs" role="tablist" aria-label="Sections of the context">
              {guide.screen.sections.map((s, i) => (
                <button key={s.name} role="tab" aria-selected={i === tab} className={i === tab ? "on" : ""} onClick={() => setTab(i)}>{s.name}</button>
              ))}
            </div>
            <div className="g-pane" role="tabpanel">
              <p>{section.why}</p>
              <pre><code>{section.text}</code></pre>
            </div>
          </div>
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">The only way to act or remember</div><h2>Its tools</h2></div></div>
        <div className="pb">
          <dl className="g-tools">
            {guide.tools.map((t) => <div key={t.call}><dt><code>{t.call}</code></dt><dd>{t.does}</dd></div>)}
          </dl>
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Who decides what</div><h2>How each one reacts</h2></div></div>
        <div className="pb g-minds">
          {guide.minds.map((m) => (
            <div key={m.who} style={c(m.colour)}>
              <h3>{m.who}</h3>
              <ul>{m.how.map((h) => <li key={h}>{h}</li>)}</ul>
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Not a mock-up</div><h2>{t.result ?? "A real game"}</h2></div></div>
        <div className="pb">
          <p className="g-lead">{guide.result.note}</p>
          <dl className="facts">{guide.result.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        </div>
      </section>
    </>
  );
}

/** A field's fire strength: it arrives at 1, grows a step a night unless watered, and is lost
 * after two nights at 5. Water takes a step off; on the day it arrives, all of it. */
function FireTrack() {
  const steps = [0, 1, 2, 3, 4, 5];
  return (
    <svg className="g-track" viewBox="0 0 420 120" role="img" aria-label="Fire strength from 1 to 5: grows by 1 a day, falls by 1 when watered, lost after 2 days at 5">
      <defs>
        <marker id="g-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--muted)" /></marker>
      </defs>
      {steps.map((s) => {
        const x = 20 + s * 66;
        const fill = s === 0 ? "var(--panel)" : `color-mix(in srgb, var(--fire) ${18 + s * 15}%, var(--panel))`;
        return (
          <g key={s}>
            <rect x={x} y={34} width={56} height={34} rx={7} fill={fill} stroke={s === 5 ? "var(--stale)" : "var(--line)"} strokeWidth={s === 5 ? 2 : 1} />
            <text x={x + 28} y={56} textAnchor="middle" fontSize={13} fill="var(--ink)">{s === 0 ? "out" : s}</text>
          </g>
        );
      })}
      <path d="M100,30 C140,6 200,6 240,30" fill="none" stroke="var(--fire)" strokeWidth={1.5} markerEnd="url(#g-arr)" />
      <text x={170} y={12} textAnchor="middle" fontSize={10.5} fill="var(--fire)">+1 a night, unwatered</text>
      <path d="M240,72 C200,96 140,96 100,72" fill="none" stroke="var(--water)" strokeWidth={1.5} markerEnd="url(#g-arr)" />
      <text x={170} y={108} textAnchor="middle" fontSize={10.5} fill="var(--water)">−1 a day, watered</text>
      <text x={76} y={84} textAnchor="middle" fontSize={9.5} fill="var(--muted)">arrives</text>
      <text x={378} y={84} textAnchor="middle" fontSize={9.5} fill="var(--stale)">2 nights: lost</text>
    </svg>
  );
}

/** The board of the seed-1 game: eight fields clockwise, the starting fire at F0, the two liars,
 * the one extra link (A1 to A3), and the hidden path F3 to F1 nobody knows of until fire uses it. */
function RingBoard() {
  const n = 8, cx = 160, cy = 150, R = 110;
  const at = (i: number) => {
    const a = -Math.PI / 2 + (i * 2 * Math.PI) / n;
    return [cx + R * Math.cos(a), cy + R * Math.sin(a)] as const;
  };
  const liars = new Set([2, 4]);
  return (
    <svg className="g-ring" viewBox="0 0 320 310" role="img" aria-label="Eight fields on a ring; fire starts at F0; A2 and A4 are liars; A1 and A3 have an extra link">
      <defs>
        <marker id="g-cw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="var(--fire)" /></marker>
      </defs>
      {Array.from({ length: n }, (_, i) => {
        const [x1, y1] = at(i), [x2, y2] = at((i + 1) % n);
        const k = 24 / Math.hypot(x2 - x1, y2 - y1);
        return <line key={i} x1={x1 + (x2 - x1) * k} y1={y1 + (y2 - y1) * k} x2={x2 - (x2 - x1) * k} y2={y2 - (y2 - y1) * k} stroke="var(--fire)" strokeOpacity={0.55} strokeWidth={1.4} markerEnd="url(#g-cw)" />;
      })}
      {(() => { const [x1, y1] = at(1), [x2, y2] = at(3); return <line x1={x1} y1={y1} x2={x2} y2={y2} stroke="var(--accent)" strokeDasharray="5 4" strokeWidth={1.3} />; })()}
      {(() => { const [x1, y1] = at(3), [x2, y2] = at(1); return <path d={`M${x1 - 16},${y1 - 12} Q${cx - 10},${cy - 10} ${x2 - 20},${y2 + 8}`} fill="none" stroke="var(--fire)" strokeDasharray="1 5" strokeWidth={2} markerEnd="url(#g-cw)" />; })()}
      <text x={cx - 6} y={cy + 4} textAnchor="middle" fontSize={10} fill="var(--muted)">hidden: F3 → F1</text>
      {Array.from({ length: n }, (_, i) => {
        const [x, y] = at(i);
        const liar = liars.has(i), fire = i === 0;
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={20} fill={fire ? "color-mix(in srgb, var(--fire) 35%, var(--panel))" : "var(--panel)"} stroke={liar ? "var(--lie)" : fire ? "var(--fire)" : "var(--ok)"} strokeWidth={liar ? 2.4 : 1.6} />
            <text x={x} y={y - 2} textAnchor="middle" fontSize={11} fill="var(--ink)">F{i}</text>
            <text x={x} y={y + 10} textAnchor="middle" fontSize={9} fill={liar ? "var(--lie)" : "var(--muted)"}>A{i}</text>
          </g>
        );
      })}
      <g fontSize={10} fill="var(--muted)">
        <text x={8} y={300}><tspan fill="var(--fire)">●</tspan> fire on day 0 · <tspan fill="var(--lie)">●</tspan> liar · <tspan fill="var(--accent)">- -</tspan> extra link · <tspan fill="var(--fire)">→</tspan> spread</text>
      </g>
    </svg>
  );
}
