import { useEffect, useState } from "react";
import { api, type RunOptions } from "./api";
import { AppsView } from "./apps/AppsView";
import { BuildView } from "./build/BuildView";
import { RunView } from "./run/RunView";
import type { RecordedRun, Summary, TeamSpec } from "./types";

type View = { kind: "build" } | { kind: "run"; id: string } | { kind: "runs" } | { kind: "apps" };

function readHash(): View {
  const m = /^#run\/(\w+)$/.exec(window.location.hash);
  if (m) return { kind: "run", id: m[1]! };
  if (window.location.hash === "#apps") return { kind: "apps" };
  return window.location.hash === "#runs" ? { kind: "runs" } : { kind: "build" };
}

export function App() {
  const [view, setView] = useState<View>(readHash);
  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const go = (next: View) => {
    window.location.hash = next.kind === "run" ? `run/${next.id}` : next.kind === "build" ? "" : next.kind;
    setView(next);
  };

  async function run(pack: string, team: TeamSpec, name: string, options: RunOptions) {
    const space = await api.create(pack, team, name, options);
    go({ kind: "run", id: space.id });
  }

  return (
    <div className="wrap">
      <header className="top">
        <div className="brand">
          <h1>Cascade</h1>
          <p>Teams of agents whose only memory is a shared belief graph · one correction reaches everything built on it</p>
        </div>
        <div className="controls">
          <nav className="seg" aria-label="Views">
            <button aria-pressed={view.kind === "apps"} onClick={() => go({ kind: "apps" })}>My apps</button>
            <button aria-pressed={view.kind === "build"} onClick={() => go({ kind: "build" })}>Build</button>
            <button aria-pressed={view.kind === "run" || view.kind === "runs"} onClick={() => go({ kind: "runs" })}>Runs</button>
          </nav>
          <ThemeToggle />
        </div>
      </header>
      {view.kind === "build" && <BuildView onRun={run} />}
      {view.kind === "run" && <RunView spaceId={view.id} onBack={() => go({ kind: "build" })} />}
      {view.kind === "runs" && <Runs onOpen={(id) => go({ kind: "run", id })} />}
      {view.kind === "apps" && <AppsView onRun={run} />}
    </div>
  );
}

const THEME = "graph-agent:theme";

/** Light, dark, or the system's choice, remembered in this browser. */
function ThemeToggle() {
  const read = () => {
    try { return localStorage.getItem(THEME) ?? "auto"; } catch { return "auto"; }
  };
  const [theme, setTheme] = useState(read);
  useEffect(() => {
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(THEME, theme); } catch { /* only a convenience */ }
  }, [theme]);
  return (
    <div className="seg" role="group" aria-label="Theme">
      {(["auto", "light", "dark"] as const).map((t) => (
        <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>{t}</button>
      ))}
    </div>
  );
}

function Runs({ onOpen }: { onOpen: (id: string) => void }) {
  const [spaces, setSpaces] = useState<Summary[] | null>(null);
  const [recorded, setRecorded] = useState<Awaited<ReturnType<typeof api.runs>>>([]);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    api.spaces().then(setSpaces).catch(() => setSpaces([]));
    api.runs().then(setRecorded).catch(() => setRecorded([]));
  }, []);
  async function replay(run: RecordedRun) {
    try { onOpen((await api.replay(run)).id); } catch (e) { setProblem((e as Error).message); }
  }
  return (
    <div className="runs">
      <section className="panel">
        <div className="ph"><div><div className="eyebrow">This session</div><h2>Runs</h2></div></div>
        <div className="pb">
          {spaces === null && <p className="none">Loading…</p>}
          {spaces?.length === 0 && <p className="none">No runs yet. Build a team and press “Run this team”.</p>}
          <ul className="bl">
            {spaces?.map((s) => (
              <li key={s.id}>
                <button className="linkish" onClick={() => onOpen(s.id)}>{s.title}</button>
                <small>{s.model} · {s.clock} · {s.finished ? "finished" : s.running ? "running" : "paused"} · {s.events} events</small>
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Real model runs, recorded</div><h2>Replay from the cache</h2></div></div>
        <div className="pb">
          <p className="note">Each of these ran with a real model. Replaying asks the model the same questions, which are all cached: it costs nothing and gives the same run, with every belief and why-chain open.</p>
          {recorded.length === 0 && <p className="none">No recorded runs yet.</p>}
          <ul className="bl">
            {recorded.map((r) => (
              <li key={r.path}>
                <button className="linkish" onClick={() => void replay(r)}>{r.pack} · {r.name}{Object.values(r.options).length ? ` · ${Object.values(r.options).filter((v) => v !== "claude-haiku-5-5").join(", ")}` : ""}</button>
                <small>{r.checks_passed !== null ? `${r.checks_passed}/${r.checks_total} checks · ` : ""}{r.path}</small>
              </li>
            ))}
          </ul>
          {problem && <p className="err">{problem}</p>}
        </div>
      </section>
    </div>
  );
}
