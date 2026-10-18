import { useEffect, useState } from "react";
import { api, type RunOptions } from "./api";
import { AppsView } from "./apps/AppsView";
import { Landing } from "./landing/Landing";
import { RunView } from "./run/RunView";
import { SettingsView } from "./settings/SettingsView";
import { SetupPage, SetupsView } from "./setups/SetupsView";
import type { Me, RecordedRun, Summary, TeamSpec } from "./types";
import logo from "./logo.svg";

type View =
  | { kind: "home" }
  | { kind: "setups" }
  | { kind: "setup"; id: string }
  | { kind: "settings" }
  | { kind: "run"; id: string }
  | { kind: "runs" }
  | { kind: "apps" };

function readHash(): View {
  const hash = window.location.hash;
  const run = /^#run\/(\w+)$/.exec(hash);
  if (run) return { kind: "run", id: run[1]! };
  const setup = /^#setup\/([\w-]+)$/.exec(hash);
  if (setup) return { kind: "setup", id: setup[1]! };
  if (hash === "#build") return { kind: "apps" }; // the old canvas: Make your own is the one editor now
  if (hash === "#apps" || hash === "#setups" || hash === "#runs" || hash === "#settings") {
    return { kind: hash.slice(1) as "apps" | "setups" | "runs" | "settings" };
  }
  return { kind: "home" }; // the landing page
}

function hashOf(view: View): string {
  if (view.kind === "run" || view.kind === "setup") return `${view.kind}/${view.id}`;
  return view.kind === "home" ? "" : view.kind;
}

export function App() {
  const [view, setView] = useState<View>(readHash);
  const [me, setMe] = useState<Me | null>(null); // hosted: who is signed in (local: no one, and no need)
  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [view.kind]); // a new page opens at its top
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe({ hosted: false, user: null }));
  }, []);
  const go = (next: View) => {
    window.location.hash = hashOf(next);
    setView(next);
  };

  async function run(pack: string, team: TeamSpec, name: string, options: RunOptions) {
    const space = await api.create(pack, team, name, options);
    go({ kind: "run", id: space.id });
  }

  if (me === null) return <p className="none pad">Connecting…</p>;
  if (me.hosted && !me.user) return <SignIn />;

  return (
    <div className="wrap">
      <header className="top">
        <div className="brand">
          <h1><img className="logo" src={logo} alt="" />Groundwork</h1>
          <p>Teams of agents whose only memory is a shared belief graph · one correction reaches everything built on it</p>
        </div>
        <div className="controls">
          <nav className="seg" aria-label="Views">
            <button aria-pressed={view.kind === "home"} onClick={() => go({ kind: "home" })}>Overview</button>
            <button aria-pressed={view.kind === "setups" || view.kind === "setup"} onClick={() => go({ kind: "setups" })}>Setups</button>
            <button aria-pressed={view.kind === "apps"} onClick={() => go({ kind: "apps" })}>Make your own</button>
            <button aria-pressed={view.kind === "run" || view.kind === "runs"} onClick={() => go({ kind: "runs" })}>Runs</button>
            <button aria-pressed={view.kind === "settings"} onClick={() => go({ kind: "settings" })}>Settings</button>
          </nav>
          <ThemeToggle />
          {me.user && (
            <div className="who">
              <span title={me.user.name}>{me.user.email}</span>
              <button className="btn" onClick={() => void api.logout().then(() => window.location.reload())}>Sign out</button>
            </div>
          )}
        </div>
      </header>
      {view.kind === "home" && <Landing onSetups={() => go({ kind: "setups" })} onOpen={(id) => go({ kind: "setup", id })} />}
      {view.kind === "setups" && <SetupsView onOpen={(id) => go({ kind: "setup", id })} />}
      {view.kind === "setup" && <SetupPage id={view.id} onBack={() => go({ kind: "setups" })} onRun={run} />}
      {view.kind === "run" && <RunView spaceId={view.id} onBack={() => go({ kind: "setups" })} />}
      {view.kind === "runs" && <Runs onOpen={(id) => go({ kind: "run", id })} />}
      {view.kind === "apps" && <AppsView onRun={run} hosted={me.hosted} />}
      {view.kind === "settings" && <SettingsView hosted={me.hosted} />}
    </div>
  );
}

/** The hosted console's front door: nothing is shown or run before signing in. */
function SignIn() {
  return (
    <div className="signin">
      <section className="panel">
        <div className="pb">
          <img className="logo big" src={logo} alt="" />
          <div className="eyebrow">Groundwork</div>
          <h1>Teams of agents with one shared memory</h1>
          <p className="note">
            Build a team, run it on a simulated week or on your own mail and calendar, and see why each agent believes what it does.
            Signing in tells Groundwork only your name and address. Gmail and Calendar are connected later, read-only, if you choose to.
          </p>
          <a className="btn primary big" href="/auth/login">Sign in with Google</a>
          <a className="linkish" href="/privacy">What Groundwork keeps, and where your data goes</a>
        </div>
      </section>
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
          {spaces?.length === 0 && <p className="none">No runs yet. Pick one of the setups and press Run.</p>}
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
