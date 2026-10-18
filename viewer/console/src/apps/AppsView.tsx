import { useEffect, useMemo, useState } from "react";
import { api, type RunOptions } from "../api";
import { c } from "../css";
import type { AgentSetup, AppsSetup, ConnectionEntry, ConnectionInfo, ConnectionTest, Keys, Preset, SetupView, TeamSpec } from "../types";
import { StreamsPanel } from "./StreamsPanel";

interface Props {
  onRun: (pack: string, team: TeamSpec, name: string, options: RunOptions) => Promise<void>;
  hosted: boolean; // several people use this console: secrets are their own keys, not .env
}

const nameOf = (e: ConnectionEntry) => String(e.name ?? e.preset ?? "");

/** Your own agents, in three steps: what the team reads (live public data, no account needed;
 * and, folded away, your own accounts: each an MCP server whose secrets stay in .env), then in a
 * few lines what each agent is for, then run it.
 * The team, its links and its safety settings are made from that (packs/apps/setup.py). You can
 * keep several teams on the same apps (one file each in my-teams/); the bar on top picks one. */
export function AppsView({ onRun, hosted }: Props) {
  const where = hosted ? "in Settings" : "in .env";
  // ---- your keys (hosted) ----
  const [keys, setKeys] = useState<Keys | null>(null);
  // ---- your apps ----
  const [presets, setPresets] = useState<Preset[]>([]);
  const [entries, setEntries] = useState<ConnectionEntry[]>([]);
  const [infos, setInfos] = useState<ConnectionInfo[]>([]);
  const [tests, setTests] = useState<Record<string, ConnectionTest>>({});
  const [testing, setTesting] = useState<string | null>(null);
  const [appsChanged, setAppsChanged] = useState(false);
  const [appsProblem, setAppsProblem] = useState("");
  // ---- your teams, and the one open ----
  const [teams, setTeams] = useState<{ id: string; name: string }[]>([]);
  const [examples, setExamples] = useState<{ id: string; name: string }[]>([]); // teams to start from
  const [teamId, setTeamId] = useState<string | null>(null); // null: not saved yet
  const [leaving, setLeaving] = useState<(() => void) | null>(null); // asked to discard changes
  // ---- its agents ----
  const [setup, setSetup] = useState<AppsSetup | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [saved, setSaved] = useState(false);
  const [agentsChanged, setAgentsChanged] = useState(false);
  // ---- running ----
  const [model, setModel] = useState("claude-haiku-5-5");
  const [approvals, setApprovals] = useState("shadow");
  const [busy, setBusy] = useState(false);
  const [runProblem, setRunProblem] = useState("");

  useEffect(() => {
    api.connections().then((r) => { setPresets(r.presets); setEntries(r.entries); setInfos(r.connections); })
      .catch((e: Error) => setAppsProblem(e.message));
    open(undefined);
    if (hosted) api.keys().then(setKeys).catch((e: Error) => setAppsProblem(e.message));
  }, [hosted]);



  function show(v: SetupView) {
    setTeams(v.teams);
    setExamples(v.examples ?? []);
    setTeamId(v.team);
    setSetup(v.setup);
    setProblems(v.problems);
    setSaved(v.saved);
    setAgentsChanged(false);
  }

  /** Open a team (undefined: your first, or the example when you have none). */
  function open(team: string | undefined) {
    api.setup("apps", team).then(show).catch((e: Error) => setProblems([e.message]));
  }

  /** Do `then`, but first ask to discard unsaved changes to the open team, if there are any. */
  function leave(then: () => void) {
    if (agentsChanged) setLeaving(() => then);
    else then();
  }

  /** A new team: from one of the examples (by its id), or blank (null). */
  function newTeam(example: string | null) {
    leave(() => {
      api.setup("apps", example ?? "example").then((v) => {
        show(v);
        setTeamId(null);
        setSaved(false);
        const blank: AppsSetup = { name: "New team", agents: [{ name: "reader", job: "", looks_after: [], apps: [] }], things: {} };
        changeSetup(example ? v.setup : blank);
      }).catch((e: Error) => setProblems([e.message]));
    });
  }

  async function deleteTeam() {
    if (!teamId) return;
    try {
      await api.deleteSetup("apps", teamId);
      open(undefined);
    } catch (e) {
      setProblems([(e as Error).message]);
    }
  }

  // the agents are checked as you type (nothing is saved until you press Save)
  useEffect(() => {
    if (!setup || !agentsChanged) return;
    const timer = setTimeout(() => {
      api.checkSetup("apps", setup).then((r) => setProblems(r.problems)).catch(() => undefined);
    }, 350);
    return () => clearTimeout(timer);
  }, [setup, agentsChanged]);

  // ---- your apps ----

  function changeEntries(next: ConnectionEntry[]) { setEntries(next); setAppsChanged(true); }
  function changeEntry(name: string, patch: Partial<ConnectionEntry>) {
    changeEntries(entries.map((e) => (nameOf(e) === name ? { ...e, ...patch } : e)));
  }

  async function saveApps() {
    try {
      const r = await api.saveConnections(entries);
      setInfos(r.connections);
      setAppsChanged(false);
      setAppsProblem("");
      if (hosted) api.keys().then(setKeys).catch(() => undefined); // the apps may want new ones
    } catch (e) {
      setAppsProblem((e as Error).message);
    }
  }

  async function test(entry: ConnectionEntry) {
    const name = nameOf(entry);
    setTesting(name);
    try {
      const result = await api.testConnection(entry);
      setTests((t) => ({ ...t, [name]: result }));
    } catch (e) {
      setTests((t) => ({ ...t, [name]: { ok: false, error: (e as Error).message } }));
    } finally {
      setTesting(null);
    }
  }

  // ---- your agents ----

  function changeSetup(next: AppsSetup) { setSetup(next); setAgentsChanged(true); }
  function changeAgent(i: number, patch: Partial<AgentSetup>) {
    if (!setup) return;
    changeSetup({ ...setup, agents: setup.agents.map((a, k) => (k === i ? { ...a, ...patch } : a)) });
  }
  function addAgent() {
    if (!setup) return;
    let n = setup.agents.length + 1;
    while (setup.agents.some((a) => a.name === `agent-${n}`)) n++;
    changeSetup({ ...setup, agents: [...setup.agents, { name: `agent-${n}`, job: "", looks_after: [], apps: [] }] });
  }

  /** Save the open team; its id when it has no problems left, else null. */
  async function saveAgents(): Promise<string | null> {
    if (!setup) return null;
    try {
      const r = await api.saveSetup("apps", setup, teamId);
      setProblems(r.problems);
      setTeamId(r.team);
      setSaved(true);
      setAgentsChanged(false);
      api.setup("apps", r.team).then((v) => setTeams(v.teams)).catch(() => undefined);
      return r.problems.length === 0 ? r.team : null;
    } catch (e) {
      setProblems([(e as Error).message]);
      return null;
    }
  }

  async function run() {
    setBusy(true);
    setRunProblem("");
    try {
      if (appsChanged) await saveApps();
      const id = await saveAgents();
      if (!id) { setRunProblem("fix what the agents panel lists first"); return; }
      const team = await api.template("apps", id);
      await onRun("apps", team, id, { model, store: "memory", options: { approvals } });
    } catch (e) {
      setRunProblem((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // the tools an agent can be given: every app as a whole, and each tool a test has listed
  const appChoices = useMemo(() => entries.map((e) => {
    const name = nameOf(e);
    return { name, all: `${name}_*`, tools: tests[name]?.tools ?? [] };
  }), [entries, tests]);

  const ready = infos.filter((i) => i.missing.length === 0).length;

  return (
    <div className="apps">
      <section className="panel teams-bar">
        <div className="ph">
          <div><div className="eyebrow">Your teams · {teams.length} saved · they share your accounts</div><h2>Team</h2></div>
        </div>
        <div className="pb">
          <div className="team-list">
            {teams.map((t) => (
              <button key={t.id} className={`tpl ${teamId === t.id ? "on" : ""}`} onClick={() => teamId !== t.id && leave(() => open(t.id))}>
                <b>{t.name}</b><small>my-teams/{t.id}.json</small>
              </button>
            ))}
            {teamId === null && setup && (
              <button className="tpl on" disabled><b>{setup.name || "New team"}</b><small>not saved yet</small></button>
            )}
          </div>
          <div className="row-btns">
            <button className="btn" onClick={() => newTeam(null)}>+ New team</button>
            {examples.map((e) => (
              <button key={e.id} className="btn" onClick={() => newTeam(e.id)}>+ New from the example: {e.name}</button>
            ))}
            {teamId && <button className="btn danger" onClick={() => void deleteTeam()}>Delete this team</button>}
          </div>
          {leaving && (
            <p className="note">
              Unsaved changes to {setup?.name}.{" "}
              <button className="linkish" onClick={() => { const then = leaving; setLeaving(null); then(); }}>Discard them</button>{" · "}
              <button className="linkish" onClick={() => setLeaving(null)}>Keep editing</button>
            </p>
          )}
        </div>
      </section>

      {keys && <KeysNote keys={keys} />}

      {setup && (
        <StreamsPanel
          streams={setup.streams ?? []}
          pace={setup.pace}
          polls={setup.polls}
          accounts={entries.length}
          onChange={(patch) => changeSetup({ ...setup, ...patch })}
        >
          <details className="accounts" open={entries.length > 0 || undefined}>
            <summary>Your own accounts · optional · {entries.length} connected · {ready} ready</summary>
            {hosted
              ? <p className="note">Gmail, Calendar, Todoist or any MCP server: it does the sign-in and the API calls. An app names the secrets it needs (like <code>$TODOIST_API_KEY</code>) and you add their values in <a className="linkish" href="#settings">Settings</a>, where they are kept encrypted and never shown again.</p>
              : <p className="note">Gmail, Calendar, Todoist or any MCP server: it does the sign-in and the API calls. Secrets never go in here: an app names them (like <code>$TODOIST_API_KEY</code>) and you put the values in <code>.env</code> at the project's root. Every team shares these.</p>}
            {entries.map((entry) => {
              const name = nameOf(entry);
              const info = infos.find((i) => i.name === name);
              return (
                <AppCard
                  key={name}
                  entry={entry}
                  info={info}
                  test={tests[name]}
                  testing={testing === name}
                  where={where}
                  onTest={() => void test(entry)}
                  onChange={(patch) => changeEntry(name, patch)}
                  onRemove={() => changeEntries(entries.filter((e) => nameOf(e) !== name))}
                />
              );
            })}
            <AddApp presets={presets} taken={entries.map(nameOf)} hosted={hosted} onAdd={(e) => changeEntries([...entries, e])} />
            {appsChanged && <div><button className="btn" onClick={() => void saveApps()}>Save accounts</button></div>}
            {appsProblem && <p className="err">{appsProblem}</p>}
          </details>
        </StreamsPanel>
      )}

      <section className="panel">
        <div className="ph">
          <div><div className="eyebrow">Step 2 · {setup?.agents.length ?? 0} agents · {saved && teamId ? `my-teams/${teamId}.json` : "not saved yet"}</div><h2>Your agents</h2></div>
          <button className="btn" disabled={!agentsChanged && saved} onClick={() => void saveAgents()}>{agentsChanged || !saved ? "Save team" : "Saved"}</button>
        </div>
        <div className="pb insp">
          {!setup && <p className="none">Loading…</p>}
          {setup && (
            <>
              <label>Team name<input value={setup.name} onChange={(e) => changeSetup({ ...setup, name: e.target.value })} /></label>
              <Kinds things={setup.things ?? {}} onChange={(things) => changeSetup({ ...setup, things })} />
              {setup.agents.map((agent, i) => (
                <AgentCard
                  key={i}
                  agent={agent}
                  others={setup.agents.filter((_, k) => k !== i).map((a) => a.name)}
                  kinds={Object.keys(setup.things ?? {})}
                  apps={appChoices}
                  onChange={(patch) => changeAgent(i, patch)}
                  onRemove={() => changeSetup({ ...setup, agents: setup.agents.filter((_, k) => k !== i) })}
                />
              ))}
              <div><button className="btn" onClick={addAgent}>+ Add an agent</button></div>
              {problems.length > 0
                ? <ul className="bl problems">{problems.map((p) => <li key={p} className="err">{p}</li>)}</ul>
                : <p className="ok-line">Ready: no problems found.</p>}
            </>
          )}
        </div>
      </section>

      <section className="panel">
        <div className="ph"><div><div className="eyebrow">Step 3</div><h2>Run it</h2></div></div>
        <div className="pb insp">
          <label>Model
            <select value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="claude-haiku-5-5">Claude Haiku 5.5 (cached)</option>
              <option value="claude-sonnet-5-5">Claude Sonnet 5.5 (cached)</option>
            </select>
          </label>
          <label>Outward actions
            <select value={approvals} onChange={(e) => setApprovals(e.target.value)}>
              <option value="shadow">Record only (never run): start here</option>
              <option value="manual">Wait for me to approve each one</option>
              <option value="auto">Run at once</option>
            </select>
          </label>
          <p className="note">A real model reads what comes in, so a run spends from {hosted ? <>your own Anthropic key (in <a className="linkish" href="#settings">Settings</a>)</> : <>the key in <code>.env</code></>} (each request is cached, so a rerun is free). A tool that changes something runs only as chosen above. What an item says is read as claims to check, never as instructions.</p>
          <div><button className="btn primary" disabled={busy || !setup} onClick={() => void run()}>{busy ? "Starting…" : "Save and run"}</button></div>
          {runProblem && <p className="err">{runProblem}</p>}
        </div>
      </section>
    </div>
  );
}

// ---- your keys (hosted) -------------------------------------------------------------------------

/** The keys a run here needs and you have not saved yet; they are kept on the Settings page. */
function KeysNote({ keys }: { keys: Keys }) {
  const missing = keys.wanted.filter((k) => !keys.saved.includes(k));
  if (missing.length === 0) return null;
  return (
    <p className="note">
      Not set yet: {missing.map((k, i) => <span key={k}>{i > 0 && ", "}<code>{k}</code></span>)}.{" "}
      Add {missing.length === 1 ? "it" : "them"} in <a className="linkish" href="#settings">Settings</a>.
    </p>
  );
}

// ---- one app ------------------------------------------------------------------------------------

function AppCard({ entry, info, test, testing, where, onTest, onChange, onRemove }: {
  entry: ConnectionEntry;
  info: ConnectionInfo | undefined;
  test: ConnectionTest | undefined;
  testing: boolean;
  where: string; // where its secrets are kept: "in .env", or "in Settings"

  onTest: () => void;
  onChange: (patch: Partial<ConnectionEntry>) => void;
  onRemove: () => void;
}) {
  const name = nameOf(entry);
  const exclude = (entry.exclude as string[] | undefined) ?? [];
  const outward = (entry.outward as Record<string, boolean> | undefined) ?? info?.outward ?? {};
  const plain = (tool: string) => tool.slice(name.length + 1); // the server's own name
  // the Google token is not a key you paste: it comes from connecting your account
  const missing = (info?.missing ?? []).map((m) => (m === "GOOGLE_ACCESS_TOKEN" ? "your Google account connected" : m));
  return (
    <div className="conn">
      <div className="conn-h">
        <b>{name}</b>
        <span className="muted">{info?.label || (entry.preset ? `preset ${entry.preset}` : String(entry.command ?? entry.url ?? ""))}</span>
        {!info && <span className="tag">not saved</span>}
        {info && (missing.length
          ? <span className="tag" style={c("var(--stale)")}>needs {missing.join(", ")} {where}</span>
          : <span className="tag" style={c("var(--ok)")}>ready</span>)}
        <span className="grow" />
        <button className="btn" disabled={testing} onClick={onTest}>{testing ? "Testing…" : "Test"}</button>
        <button className="btn" onClick={onRemove} aria-label={`Remove ${name}`}>Remove</button>
      </div>
      {info?.about && <p className="note">{info.about}</p>}
      {test && !test.ok && <p className="err">{test.error}</p>}
      {test?.ok && (
        <>
          <ul className="bl feeds">
            {(test.feeds ?? []).map((f) => (
              <li key={f.name}>
                <span>news from <b>{f.name}</b></span>
                {f.sign_in && <a className="btn" href={f.sign_in} target="_blank" rel="noreferrer">Sign in, then Test again</a>}
                {f.error && <small className="err">{f.error}</small>}
                {f.items !== undefined && <small>{f.items} found{f.sample?.length ? `: ${f.sample.join(" · ")}` : ""}</small>}
              </li>
            ))}
          </ul>
          <table className="tools">
            <thead><tr><th>Tool</th><th>Offer it</th><th>Asks you first</th></tr></thead>
            <tbody>
              {(test.tools ?? []).map((t) => (
                <tr key={t.name} title={t.description}>
                  <td><code>{t.name}</code></td>
                  <td><input type="checkbox" checked={!exclude.includes(plain(t.name))} onChange={(e) => onChange({ exclude: e.target.checked ? exclude.filter((x) => x !== plain(t.name)) : [...exclude, plain(t.name)] })} /></td>
                  <td><input type="checkbox" checked={outward[plain(t.name)] ?? t.outward} onChange={(e) => onChange({ outward: { ...outward, [plain(t.name)]: e.target.checked } })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {exclude.length > 0 && <p className="note">Not offered: {exclude.map((x) => <button key={x} className="chip" onClick={() => onChange({ exclude: exclude.filter((y) => y !== x) })}>{x} ↺</button>)}</p>}
          <p className="note">A tool that changes something (sends, books, writes) asks you first, or is only recorded, depending on how you run. Unknown tools ask first.</p>
        </>
      )}
    </div>
  );
}

function AddApp({ presets, taken, hosted, onAdd }: { presets: Preset[]; taken: string[]; hosted: boolean; onAdd: (e: ConnectionEntry) => void }) {
  const [custom, setCustom] = useState(false);
  const [name, setName] = useState("");
  // hosted: an app of your own is a server on the internet; nobody starts commands on the server
  const [how, setHow] = useState<"command" | "url">(hosted ? "url" : "command");
  const [command, setCommand] = useState("");
  const [args, setArgs] = useState("");
  const [url, setUrl] = useState("");
  const [secrets, setSecrets] = useState("");
  const [problem, setProblem] = useState("");

  function add() {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) return setProblem("name: lowercase letters, digits and -");
    if (taken.includes(name)) return setProblem(`there is already an app named ${name}`);
    // "API_KEY=$NOTES_KEY" lines: what the server reads, and the .env name it comes from
    const env: Record<string, string> = {};
    for (const line of secrets.split("\n").map((l) => l.trim()).filter(Boolean)) {
      const [key, ...rest] = line.split("=");
      env[key!.trim()] = rest.join("=").trim();
    }
    const entry: ConnectionEntry = how === "command"
      ? { name, command, args: args.split(/\s+/).filter(Boolean), env }
      : { name, url, headers: env };
    onAdd(entry);
    setCustom(false); setName(""); setCommand(""); setArgs(""); setUrl(""); setSecrets(""); setProblem("");
  }

  const free = presets.filter((p) => !taken.includes(p.name));
  return (
    <div className="add-app">
      <div className="eyebrow">Add an app</div>
      <div className="kinds">
        {free.map((p) => (
          <button key={p.name} className="btn" title={p.about} onClick={() => onAdd({ preset: p.name })}>+ {p.label}</button>
        ))}
        <button className="btn" aria-pressed={custom} onClick={() => setCustom(!custom)}>+ Any MCP server…</button>
      </div>
      {custom && (
        <div className="insp custom">
          <label>Name (its tools are called name_tool)<input value={name} onChange={(e) => setName(e.target.value)} placeholder="notes" /></label>
          {!hosted && (
            <div className="seg" role="group" aria-label="How to reach it">
              <button aria-pressed={how === "command"} onClick={() => setHow("command")}>Start a command</button>
              <button aria-pressed={how === "url"} onClick={() => setHow("url")}>A URL</button>
            </div>
          )}
          {how === "command" ? (
            <>
              <label>Command<input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx" /></label>
              <label>Arguments<input value={args} onChange={(e) => setArgs(e.target.value)} placeholder="-y some-mcp-server" /></label>
            </>
          ) : (
            <label>URL<input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example.com/mcp" /></label>
          )}
          <label>{how === "command" ? "Settings it reads" : "Headers"}, one per line, secrets as $NAME from {hosted ? "Settings" : ".env"}
            <textarea rows={2} value={secrets} onChange={(e) => setSecrets(e.target.value)} placeholder={how === "command" ? "API_KEY=$NOTES_KEY" : "Authorization=Bearer $NOTES_TOKEN"} />
          </label>
          <div><button className="btn" onClick={add}>Add it</button></div>
          {problem && <p className="err">{problem}</p>}
        </div>
      )}
    </div>
  );
}

// ---- one agent ----------------------------------------------------------------------------------

function AgentCard({ agent, others, kinds, apps, onChange, onRemove }: {
  agent: AgentSetup;
  others: string[];
  kinds: string[];
  apps: { name: string; all: string; tools: { name: string; outward: boolean }[] }[];
  onChange: (patch: Partial<AgentSetup>) => void;
  onRemove: () => void;
}) {
  const given = agent.apps ?? [];
  const toggle = (list: string[], x: string) => (list.includes(x) ? list.filter((y) => y !== x) : [...list, x]);
  const everyone = agent.talks_to === null || agent.talks_to === undefined;
  return (
    <fieldset className="agent">
      <legend>{agent.name || "unnamed"}{agent.carries_out ? " · carries out plans" : ""}</legend>
      <div className="row2">
        <label>Name<input value={agent.name} onChange={(e) => onChange({ name: e.target.value })} /></label>
        <button className="btn" onClick={onRemove}>Remove</button>
      </div>
      <label>Its job, in your words<textarea rows={3} value={agent.job} onChange={(e) => onChange({ job: e.target.value })} placeholder="Keep each quake's magnitude, and say when the agencies disagree." /></label>
      <div className="sub">Looks after</div>
      {kinds.length === 0
        ? <small className="muted">Nothing to pick: the team keeps track of no kinds yet. Until then this agent gets what nobody else looks after.</small>
        : (
          <div className="kinds">
            {kinds.map((k) => (
              <label key={k} className="check"><input type="checkbox" checked={(agent.looks_after ?? []).includes(k)} onChange={() => onChange({ looks_after: toggle(agent.looks_after ?? [], k) })} /> {k}</label>
            ))}
          </div>
        )}
      {apps.length > 0 && (
        <>
          <div className="sub">May use</div>
          {apps.map((app) => (
            <div key={app.name} className="kinds">
              <label className="check"><input type="checkbox" checked={given.includes(app.all)} onChange={() => onChange({ apps: toggle(given, app.all) })} /> all of <b>{app.name}</b></label>
              {!given.includes(app.all) && app.tools.map((t) => (
                <label key={t.name} className="check"><input type="checkbox" checked={given.includes(t.name)} onChange={() => onChange({ apps: toggle(given, t.name) })} /> {t.name.slice(app.name.length + 1)}{t.outward && <span className="tag" style={c("var(--fire)")}>asks first</span>}</label>
              ))}
              {!given.includes(app.all) && app.tools.length === 0 && <small className="muted">(press Test on {app.name} to pick single tools)</small>}
            </div>
          ))}
        </>
      )}
      {given.filter((g) => !apps.some((a) => a.all === g || a.tools.some((t) => t.name === g))).map((g) => (
        <small key={g} className="muted">also: <code>{g}</code> <button className="chip" onClick={() => onChange({ apps: given.filter((x) => x !== g) })}>remove</button></small>
      ))}
      <details className="more">
        <summary>More: who it talks to, whether it acts</summary>
        <div className="sub">Talks to</div>
        <div className="kinds">
          <label className="check"><input type="checkbox" checked={everyone} onChange={(e) => onChange({ talks_to: e.target.checked ? null : [...others] })} /> everyone</label>
          {!everyone && others.map((o) => (
            <label key={o} className="check"><input type="checkbox" checked={(agent.talks_to ?? []).includes(o)} onChange={() => onChange({ talks_to: toggle(agent.talks_to ?? [], o) })} /> {o}</label>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={!!agent.carries_out} onChange={(e) => onChange({ carries_out: e.target.checked })} /> It carries out the team's plans with its tools: it reads nothing that comes in, and is woken by what teammates send it</label>
      </details>
    </fieldset>
  );
}

// ---- kinds of thing -----------------------------------------------------------------------------

/** The kinds of thing the team keeps track of, and what can be said about each: what items are
 * about, so the router knows whose they are. A team has its own (an example brings its own). */
function Kinds({ things, onChange }: { things: Record<string, string[]>; onChange: (things: Record<string, string[]>) => void }) {
  const [kind, setKind] = useState("");
  const [facts, setFacts] = useState("");
  function add() {
    const name = kind.trim().replace(/^\w/, (x) => x.toUpperCase());
    const list = facts.split(",").map((f) => f.trim().toLowerCase().replace(/\s+/g, "_")).filter(Boolean);
    if (!name || list.length === 0) return;
    onChange({ ...things, [name]: list });
    setKind(""); setFacts("");
  }
  const remove = (k: string) => onChange(Object.fromEntries(Object.entries(things).filter(([x]) => x !== k)));
  return (
    <div className="kinds-of">
      <div className="sub">What the team keeps track of</div>
      {Object.keys(things).length === 0
        ? <small className="muted">Nothing yet. Add the kinds of thing items are about, and what can be said of each: a Quake with magnitude, place, time; an Invoice with due, amount.</small>
        : (
          <ul className="bl">
            {Object.entries(things).map(([k, f]) => (
              <li key={k}><span><b>{k}</b>: {f.join(", ")}</span><button className="chip" onClick={() => remove(k)}>remove</button></li>
            ))}
          </ul>
        )}
      <div className="row2">
        <input value={kind} onChange={(e) => setKind(e.target.value)} placeholder="Quake" aria-label="New kind" />
        <input value={facts} onChange={(e) => setFacts(e.target.value)} placeholder="magnitude, place, time" aria-label="What can be said about it" />
        <button className="btn" disabled={!kind.trim() || !facts.trim()} onClick={add}>Add</button>
      </div>
    </div>
  );
}
