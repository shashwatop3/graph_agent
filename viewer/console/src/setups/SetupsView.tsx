import { useEffect, useState } from "react";
import { api, type RunOptions } from "../api";
import { c } from "../css";
import type { StreamPeek, TeamSpec } from "../types";
import { SETUPS, setupById, type Setup } from "./content";
import { GuideView } from "./GuideView";
import { TeamDiagram } from "./TeamDiagram";

type Run = (pack: string, team: TeamSpec, name: string, options: RunOptions) => Promise<void>;

/** The setups page: how to try a setup, step by step, what each one shows, and a card for each. */
export function SetupsView({ onOpen }: { onOpen: (id: string) => void }) {
  return (
    <div className="setups">
      <section className="setups-hero">
        <div className="eyebrow">Four ready-made teams</div>
        <h2>Pick a team and watch the graph do the work</h2>
        <p>Each setup is a full team with its own world: a real day replayed, a live feed, a simulation or a scripted week. Three run free with a scripted stand-in; all four can run on a real Claude model with your own key.</p>
      </section>
      <ol className="tutorial">
        <li><h3>Pick a setup</h3><p>Open one below and read its story: what happens, who is on the team, what to watch for. The team diagram is drawn from the team that will run.</p></li>
        <li><h3>Choose a model</h3><p><b>Scripted stand-in</b> is free and instant, the same every time. A real model (Haiku or Sonnet) needs your Anthropic key in <a className="linkish" href="#settings">Settings</a>; every request is cached, so a rerun is free.</p></li>
        <li><h3>Run, then play</h3><p>Press Run. On the timeline, <b>Step ⏵</b> plays one tick, or play to the end. The network shows who told whom: a message not believed is drawn in magenta, a cut trust in red.</p></li>
        <li><h3>Ask why</h3><p>Click an agent to see what it heard, thought, said and believes. Click one of its beliefs for the why-chain: the observations behind it and the route each took, and open the <b>Memory</b> tab for corrections and what they changed.</p></li>
      </ol>
      <section className="panel">
        <div className="ph"><div><div className="eyebrow">At a glance</div><h2>What each one shows</h2></div></div>
        <div className="pb">
          <table className="proves">
            <thead><tr><th>Setup</th><th>What happens</th><th>What the graph does</th><th>Cost</th></tr></thead>
            <tbody>
              <tr><td><b>Fire sim</b></td><td>Eight keepers warn each other about a spreading fire; two of them lie.</td><td>Traces each warning along its relay route, blames the liar, forgives the honest relays.</td><td>Free (stand-in)</td></tr>
              <tr><td><b>Team offsite</b></td><td>Five desks plan an offsite; the date moves, a guest drops out, a scam arrives.</td><td>One correction reaches exactly the plans built on it. Compare with the shared-notes baseline.</td><td>Free (stand-in)</td></tr>
              <tr><td><b>Quake replay</b></td><td>The first hour after the 2024 Hualien M7.4, from five sources' real records.</td><td>Keeps three quakes in one place apart; a review reaches exactly the bulletin and alerts built on the early figure.</td><td>Free (stand-in)</td></tr>
              <tr><td><b>Live quake desk</b></td><td>Agencies and Bluesky report the same quakes, live.</td><td>Many reports meet on one quake; revisions supersede; a poster caught exaggerating is distrusted.</td><td>A real model</td></tr>
            </tbody>
          </table>
        </div>
      </section>
      <SetupCards onOpen={onOpen} />
    </div>
  );
}

/** A card for each setup, opening its page. */
export function SetupCards({ onOpen }: { onOpen: (id: string) => void }) {
  return (
    <div className="setup-cards">
      {SETUPS.map((s) => (
        <button key={s.id} className="setup-card" style={c(s.colour)} onClick={() => onOpen(s.id)}>
          <Motif id={s.id} />
          <span className="tag">{s.kind}</span>
          <h3>{s.title}</h3>
          <p>{s.tagline}</p>
          <span className="more">Read about it, then run it →</span>
        </button>
      ))}
    </div>
  );
}

/** One setup's page: what happens, who is on the team, what to watch for, and running it. */
export function SetupPage({ id, onBack, onRun }: { id: string; onBack: () => void; onRun: Run }) {
  const setup = setupById(id);
  const [team, setTeam] = useState<TeamSpec | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (!setup) return;
    setTeam(null);
    api.template(setup.pack, setup.template).then(setTeam).catch((e: Error) => setProblem(e.message));
  }, [setup]);
  if (!setup) return <p className="none pad">No such setup. <button className="linkish" onClick={onBack}>All setups</button></p>;
  return (
    <div className="setup-page" style={c(setup.colour)}>
      <button className="linkish back" onClick={onBack}>← All setups</button>
      <section className="setup-hero">
        <Motif id={setup.id} />
        <div>
          <span className="tag">{setup.kind}</span>
          <h2>{setup.title}</h2>
          <p>{setup.tagline}</p>
          <dl className="facts">
            {setup.facts.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
          </dl>
        </div>
      </section>
      <div className="setup-cols">
        <div className="setup-main">
          {setup.guide && <GuideView guide={setup.guide} />}
          {setup.story.length > 0 && <section className="panel">
            <div className="ph"><div><div className="eyebrow">What happens</div><h2>{setup.guide ? "This game, day by day" : "The story"}</h2></div></div>
            <ol className="story">
              {setup.story.map((step, i) => (
                <li key={i} className={step.tone ?? ""}>
                  <span className="when">{step.when}</span>
                  <p>{step.what}</p>
                </li>
              ))}
            </ol>
          </section>}
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">Drawn from the team that runs</div><h2>The team</h2></div></div>
            <div className="pb">
              {team ? <TeamDiagram team={team} layout={setup.layout} /> : <p className="none">{problem || "Loading the team…"}</p>}
              <ul className="roster">
                {setup.team.map((t) => <li key={t.node}><b>{t.node}</b><span>{t.does}</span></li>)}
              </ul>
            </div>
          </section>
          <section className="panel">
            <div className="ph"><div><div className="eyebrow">While it runs</div><h2>What to watch for</h2></div></div>
            <div className="pb watch">
              {setup.watch.map((w) => <div key={w.title}><h3>{w.title}</h3><p>{w.body}</p></div>)}
            </div>
          </section>
        </div>
        <aside className="setup-side">
          <RunPanel setup={setup} team={team} onRun={onRun} />
          {setup.id === "quake-desk" && <RightNow />}
          {setup.id === "quake-desk" && (
            <section className="panel">
              <div className="ph"><div><div className="eyebrow">Free, and the same every time</div><h2>A real day, replayed</h2></div></div>
              <div className="pb"><p className="note">The same desk on the first hour of the 2024 Hualien earthquake, from the agencies' archived records: three quakes, an early figure revised, a post that lies. <a className="linkish" href="#setup/quake-day">Open the replay</a>.</p></div>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

function RunPanel({ setup, team, onRun }: { setup: Setup; team: TeamSpec | null; onRun: Run }) {
  const [model, setModel] = useState(setup.models[0]!.value);
  const [memory, setMemory] = useState("graph");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  async function start() {
    if (!team) return;
    setBusy(true);
    setProblem("");
    try {
      const options = { ...setup.options, ...(setup.memory ? { memory } : {}) };
      await onRun(setup.pack, team, setup.title, { model, options } as RunOptions);
    } catch (e) {
      setProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel run-panel">
      <div className="ph"><div><div className="eyebrow">Ready</div><h2>Run it</h2></div></div>
      <div className="pb insp">
        <div className="choices" role="radiogroup" aria-label="Model">
          {setup.models.map((m) => (
            <label key={m.value} className={`choice ${model === m.value ? "on" : ""}`}>
              <input type="radio" name="model" checked={model === m.value} onChange={() => setModel(m.value)} />
              <span><b>{m.label}</b><small>{m.note}</small></span>
            </label>
          ))}
        </div>
        {setup.memory && (
          <div className="seg" role="group" aria-label="Memory">
            <button aria-pressed={memory === "graph"} onClick={() => setMemory("graph")}>Shared graph</button>
            <button aria-pressed={memory === "notes"} onClick={() => setMemory("notes")}>Shared notes (the baseline)</button>
          </div>
        )}
        {setup.memory && memory === "notes" && <p className="note">The same team with one shared notes file instead of the graph: nothing tells a desk what rested on a fact that changed. Run both and compare the checks.</p>}
        {setup.id === "quake-desk" && <p className="note">Outward actions are only recorded. A real model reads each item once (about 50 to 100 short requests in a run), from your Anthropic key in <a className="linkish" href="#settings">Settings</a> (or <code>.env</code> when it runs on your machine).</p>}
        <button className="btn primary big" disabled={!team || busy} onClick={() => void start()}>{busy ? "Starting…" : `Run ${setup.title.split(":")[0]}`}</button>
        {problem && <p className="err">{problem}</p>}
        {setup.pack === "apps" && <p className="note">To change its streams or agents, start from it under <a className="linkish" href="#apps">Make your own</a>.</p>}
      </div>
    </section>
  );
}

/** The quake desk's sources, read now: the latest quakes USGS has (the same stream the desk reads). */
function RightNow() {
  const [peek, setPeek] = useState<StreamPeek | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    api.peekStream({ preset: "usgs-quakes", most: 4 }).then(setPeek).catch((e: Error) => setProblem(e.message));
  }, []);
  return (
    <section className="panel right-now">
      <div className="ph"><div><div className="eyebrow"><i className="live" /> Live, read just now</div><h2>Right now at USGS</h2></div></div>
      <div className="pb">
        {!peek && !problem && <p className="none">Reading the USGS feed…</p>}
        {(problem || peek?.error) && <p className="none">Could not read it just now: {problem || peek?.error}</p>}
        {peek && !peek.error && (
          <ul className="bl">
            {[...peek.items].reverse().map((q, i) => {
              const mag = /M (\d+(\.\d+)?)/.exec(q.subject)?.[1];
              return <li key={i}><span><b className="mag">{mag ?? "?"}</b> {q.subject.replace(/^M [\d.]+ - /, "")}</span></li>;
            })}
          </ul>
        )}
        <p className="note">Magnitude 4.5 and up, worldwide, the last day. The desk reads this every 30 seconds, beside EMSC, GDACS and Bluesky.</p>
      </div>
    </section>
  );
}

/** A small drawing for each setup: seismic waves, a ring of fields with a fire, a calendar page
 * whose date moves. */
function Motif({ id }: { id: string }) {
  if (id.startsWith("quake")) {
    return (
      <svg className="motif" viewBox="0 0 120 80" aria-hidden="true">
        <path d="M4 40 H30 L36 22 L44 60 L52 12 L60 66 L68 28 L74 48 L80 40 H116" fill="none" stroke="var(--c)" strokeWidth="2.4" strokeLinejoin="round" />
        {[14, 24, 34].map((r) => <circle key={r} cx="56" cy="40" r={r} fill="none" stroke="var(--c)" strokeOpacity={0.6 - r / 80} />)}
      </svg>
    );
  }
  if (id === "fire") {
    return (
      <svg className="motif" viewBox="0 0 120 80" aria-hidden="true">
        {Array.from({ length: 8 }, (_, i) => {
          const a = -Math.PI / 2 + (i * Math.PI) / 4;
          const liar = i === 2 || i === 4;
          return <circle key={i} cx={60 + 30 * Math.cos(a)} cy={40 + 30 * Math.sin(a)} r={6} fill="var(--panel)" stroke={liar ? "var(--lie)" : "var(--c)"} strokeWidth={liar ? 2.2 : 1.6} />;
        })}
        <path d="M60 26 C70 36 68 48 60 52 C52 48 50 36 60 26 Z" fill="var(--c)" />
      </svg>
    );
  }
  return (
    <svg className="motif" viewBox="0 0 120 80" aria-hidden="true">
      <rect x="22" y="12" width="62" height="56" rx="7" fill="var(--panel)" stroke="var(--c)" strokeWidth="1.8" />
      <rect x="22" y="12" width="62" height="14" rx="7" fill="var(--c)" opacity="0.85" />
      <text x="53" y="52" textAnchor="middle" fontSize="20" fontFamily="var(--f-display)" fill="var(--muted)" textDecoration="line-through">Fri</text>
      <path d="M78 46 C92 40 98 30 96 20" fill="none" stroke="var(--c)" strokeWidth="1.8" />
      <text x="100" y="16" fontSize="13" fontFamily="var(--f-display)" fill="var(--c)" textAnchor="middle">Sat</text>
    </svg>
  );
}
