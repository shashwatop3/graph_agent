import { useState } from "react";
import { c } from "../css";
import "../landing/landing.css";
import { FirePlayback } from "./FirePlayback";
import type { Guide, Icon } from "./guide";
import { QuakeGraph } from "./QuakeGraph";
import day from "./quakeDay.json";
import { MatchTimeline } from "./Visuals";

/** A setup's explainer in pictures (guide.ts): the game playing out, the rules as tiles, an
 * agent's turn in three steps (its real context behind a toggle), who decides what, the result. */
export function GuideView({ guide }: { guide: Guide }) {
  const fire = guide.visual === "fire";
  return (
    <>
      <section className="panel">
        <div className="pb g-hero">
          <p className="g-lede">{guide.lede}</p>
          {fire
            ? <div className="g-play"><FirePlayback /><Tiles tiles={guide.tiles} /></div>
            : <Tiles tiles={guide.tiles} />}
        </div>
      </section>

      {!fire && (
        <>
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">No report names its quake</div><h2>Which quake is it?</h2></div></div>
            <div className="pb">
              <MatchTimeline />
              <details className="g-more">
                <summary>All 13 matches</summary>
                <table className="g-match">
                  <tbody>
                    {(day.matched as { report: string; quake: string; why: string }[]).map((m) => (
                      <tr key={m.report}><td>{m.report}</td><td>{m.quake}</td><td className="why">{m.why}</td></tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </div>
          </section>
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">One free replay, minute by minute</div><h2>The graph</h2></div></div>
            <div className="pb"><QuakeGraph captions={guide.captions} /></div>
          </section>
        </>
      )}

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Every turn</div><h2>{fire ? "A keeper's turn" : "A desk's turn"}</h2></div></div>
        <div className="pb">
          <Turn turn={guide.turn} />
          <details className="g-more">
            <summary>See the real screen ({guide.screen.who})</summary>
            <Screen guide={guide} />
          </details>
        </div>
      </section>

      <section className="panel">
        <div className="pb g-end">
          <div className="g-minds">
            {guide.minds.map((m) => <div key={m.who} style={c(m.colour)}><b>{m.who}</b><span>{m.line}</span></div>)}
          </div>
          <div className="g-stats">
            {guide.result.facts.map(([n, label]) => <div key={label}><b>{n}</b><span>{label}</span></div>)}
          </div>
        </div>
      </section>
    </>
  );
}

function Tiles({ tiles }: { tiles: Guide["tiles"] }) {
  return (
    <div className="g-tiles">
      {tiles.map((t) => (
        <div key={t.title} className="g-tile">
          <Glyph icon={t.icon} rank={t.rank} />
          <div><b>{t.title}</b><span>{t.line}</span></div>
        </div>
      ))}
    </div>
  );
}

/** Reads → acts → the graph records it, each step lighting up in turn. */
function Turn({ turn }: { turn: Guide["turn"] }) {
  return (
    <div className="g-turn">
      <div className="g-step s1">
        <div className="eyebrow">1 · reads its graph</div>
        <div className="g-mini">{turn.reads.map((r) => <code key={r}>{r}</code>)}</div>
      </div>
      <span className="g-arrow" aria-hidden="true">→</span>
      <div className="g-step s2">
        <div className="eyebrow">2 · acts with tools</div>
        <div className="g-chips">{turn.acts.map((a) => <span key={a}>{a}</span>)}</div>
      </div>
      <span className="g-arrow" aria-hidden="true">→</span>
      <div className="g-step s3">
        <div className="eyebrow">3 · the graph records it</div>
        <div className="g-chips out">{turn.graph.map((g) => <span key={g}>{g}</span>)}</div>
      </div>
    </div>
  );
}

function Screen({ guide }: { guide: Guide }) {
  const [tab, setTab] = useState(0);
  const section = guide.screen.sections[tab]!;
  return (
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
  );
}

function Glyph({ icon, rank }: { icon: Icon; rank?: number }) {
  const body: Record<Icon, JSX.Element> = {
    fire: <path d="M16 4 C22 11 24 17 20 23 C18 26 14 26 12 23 C9 19 11 15 13 13 C13 16 14 17 15 17 C15 12 14 8 16 4 Z" fill="var(--fire)" />,
    water: <path d="M16 5 C21 12 23 16 23 19 A7 7 0 0 1 9 19 C9 16 11 12 16 5 Z" fill="var(--water)" />,
    message: <><circle cx="8" cy="16" r="4" fill="var(--accent)" /><circle cx="24" cy="16" r="4" fill="var(--accent)" opacity=".5" /><path d="M12 16 H20" stroke="var(--accent)" strokeWidth="2" strokeDasharray="2 2" /></>,
    liar: <><circle cx="16" cy="16" r="10" fill="none" stroke="var(--lie)" strokeWidth="2.4" /><path d="M11 14 h3 M18 14 h3 M11 20 Q16 17 21 20" stroke="var(--lie)" strokeWidth="2" fill="none" /></>,
    offline: <><path d="M10 10 A9 9 0 1 0 22 10" fill="none" stroke="var(--muted)" strokeWidth="2.4" /><path d="M16 5 V16" stroke="var(--muted)" strokeWidth="2.4" /></>,
    goal: <><circle cx="16" cy="16" r="10" fill="none" stroke="var(--ok)" strokeWidth="2" /><circle cx="16" cy="16" r="5" fill="none" stroke="var(--ok)" strokeWidth="2" /><circle cx="16" cy="16" r="1.8" fill="var(--ok)" /></>,
    authority: <>{[0, 1, 2].map((k) => <circle key={k} cx={8 + k * 8} cy="16" r="3.4" fill={k < (rank ?? 0) ? "var(--accent)" : "none"} stroke="var(--accent)" strokeWidth="1.4" />)}</>,
    post: <path d="M6 8 H26 V21 H14 L9 26 V21 H6 Z" fill="none" stroke="var(--lie)" strokeWidth="2" />,
    match: <><circle cx="10" cy="22" r="3" fill="var(--water)" /><circle cx="22" cy="22" r="3" fill="var(--gold)" /><path d="M10 19 L16 9 L22 19" fill="none" stroke="var(--muted)" strokeWidth="1.6" /><circle cx="16" cy="8" r="3.4" fill="var(--accent)" /></>,
  };
  return <svg className="g-glyph" viewBox="0 0 32 32" aria-hidden="true">{body[icon]}</svg>;
}
