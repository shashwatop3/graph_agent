import { useEffect, useState } from "react";
import { api } from "../api";
import { c } from "../css";
import "../landing/landing.css";
import type { Keys } from "../types";

const ANTHROPIC = "ANTHROPIC_API_KEY";

/** Settings: the Anthropic key a real model run spends from, the other keys your apps want,
 * Google, and the account. Hosted, each is the person's own, kept encrypted on the server: a value
 * is sent once, when it is saved, and never shown again. Local, every key comes from .env. */
export function SettingsView({ hosted }: { hosted: boolean }) {
  const [keys, setKeys] = useState<Keys | null>(null);
  const [problem, setProblem] = useState("");
  useEffect(() => {
    if (hosted) api.keys().then(setKeys).catch((e: Error) => setProblem(e.message));
  }, [hosted]);

  if (!hosted) {
    return (
      <div className="settings">
        <section className="panel">
          <div className="ph"><div><div className="eyebrow">Running on your machine</div><h2>Anthropic API key</h2></div></div>
          <div className="pb">
            <p className="lead">This console reads every key from <code>.env</code> at the project's root, so nothing secret goes through the browser. Add your key there and restart the console:</p>
            <pre><code>ANTHROPIC_API_KEY=sk-ant-…</code></pre>
            <p className="note">The scripted stand-in needs no key. A real model run (Haiku or Sonnet) spends from this one; every request is cached, so a rerun costs nothing. An app's own keys, like <code>TODOIST_API_KEY</code>, go in the same file.</p>
          </div>
        </section>
      </div>
    );
  }
  if (!keys) return <div className="settings"><p className="none pad">{problem || "Loading your keys…"}</p></div>;
  const change = (patch: Partial<Keys>) => setKeys((k) => (k ? { ...k, ...patch } : k));
  return (
    <div className="settings">
      <AnthropicKey saved={keys.saved.includes(ANTHROPIC)} onChange={change} />
      <OtherKeys keys={keys} onChange={change} />
      <Account />
    </div>
  );
}

function AnthropicKey({ saved, onChange }: { saved: boolean; onChange: (patch: Partial<Keys>) => void }) {
  const [value, setValue] = useState("");
  const [problem, setProblem] = useState("");
  async function save() {
    try {
      onChange({ saved: (await api.saveKey(ANTHROPIC, value.trim())).saved });
      setValue("");
      setProblem("");
    } catch (e) {
      setProblem((e as Error).message);
    }
  }
  async function remove() {
    try { onChange({ saved: (await api.deleteKey(ANTHROPIC)).saved }); } catch (e) { setProblem((e as Error).message); }
  }
  return (
    <section className="panel">
      <div className="ph">
        <div><div className="eyebrow">Kept encrypted · never shown again</div><h2>Anthropic API key</h2></div>
        <span className="tag" style={c(saved ? "var(--ok)" : "var(--stale)")}>{saved ? "saved" : "not set"}</span>
      </div>
      <div className="pb insp">
        <p className="lead">
          A real model run (Claude Haiku or Sonnet) spends from your own key. Get one at{" "}
          <a className="linkish" href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer">console.anthropic.com</a>.
          The scripted stand-in needs none.
        </p>
        <div className="key-hero">
          <input type="password" autoComplete="off" aria-label="Anthropic API key" placeholder={saved ? "Paste a new key to replace it" : "sk-ant-…"} value={value} onChange={(e) => setValue(e.target.value)} />
          <button className="btn primary" disabled={!value.trim()} onClick={() => void save()}>Save</button>
          {saved && <button className="btn danger" onClick={() => void remove()}>Remove</button>}
        </div>
        {problem && <p className="err">{problem}</p>}
        <p className="note">Only your runs use it. Every request is cached, so replaying a run costs nothing. Once saved, the key can be replaced or removed, never read back.</p>
      </div>
    </section>
  );
}

/** Google, and the keys your apps name (like TODOIST_API_KEY), each saved or removed by name. */
function OtherKeys({ keys, onChange }: { keys: Keys; onChange: (patch: Partial<Keys>) => void }) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [other, setOther] = useState("");
  const [extra, setExtra] = useState<string[]>([]); // names added here, not saved yet
  const [problem, setProblem] = useState("");
  const names = [...new Set([...keys.wanted, ...keys.saved, ...extra])].filter((n) => n !== ANTHROPIC).sort();

  async function save(name: string) {
    try {
      const r = await api.saveKey(name, values[name] ?? "");
      setValues((v) => ({ ...v, [name]: "" }));
      setProblem("");
      onChange({ saved: r.saved });
    } catch (e) {
      setProblem((e as Error).message);
    }
  }
  async function remove(name: string) {
    try { onChange({ saved: (await api.deleteKey(name)).saved }); } catch (e) { setProblem((e as Error).message); }
  }
  async function disconnect() {
    try { onChange(await api.disconnectGoogle()); } catch (e) { setProblem((e as Error).message); }
  }

  return (
    <section className="panel">
      <div className="ph"><div><div className="eyebrow">For Make your own</div><h2>Accounts and app keys</h2></div></div>
      <div className="pb insp">
        <p className="note">An app's token, like Todoist's, comes from that app's settings. The apps you add under Make your own list the names they need here.</p>
        <div className="key-row">
          <code>Google</code>
          <span className="tag" style={c(keys.google ? "var(--ok)" : "var(--stale)")}>{keys.google ? "connected" : "not connected"}</span>
          <span className="muted grow">Gmail and Calendar, read-only: Groundwork can never send, delete or change anything there</span>
          {keys.google
            ? <button className="btn danger" onClick={() => void disconnect()}>Disconnect</button>
            : <a className="btn primary" href="/auth/google">Connect Gmail and Calendar</a>}
        </div>
        {names.map((name) => {
          const saved = keys.saved.includes(name);
          return (
            <div key={name} className="key-row">
              <code>{name}</code>
              <span className="tag" style={c(saved ? "var(--ok)" : "var(--stale)")}>{saved ? "saved" : "not set"}</span>
              <input type="password" autoComplete="off" placeholder={saved ? "replace it" : "paste it here"} value={values[name] ?? ""} onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))} />
              <button className="btn" disabled={!(values[name] ?? "").trim()} onClick={() => void save(name)}>Save</button>
              {saved && <button className="btn danger" onClick={() => void remove(name)}>Remove</button>}
            </div>
          );
        })}
        <label>Another key, by the name an app uses<input value={other} placeholder="NOTES_TOKEN" onChange={(e) => setOther(e.target.value.toUpperCase())} /></label>
        <div><button className="btn" disabled={!/^[A-Z_][A-Z0-9_]*$/.test(other)} onClick={() => { setExtra((x) => [...x, other]); setOther(""); }}>+ Add it to the list</button></div>
        {problem && <p className="err">{problem}</p>}
      </div>
    </section>
  );
}

function Account() {
  const [deleting, setDeleting] = useState(false); // asked to confirm deleting the account
  const [problem, setProblem] = useState("");
  async function deleteAccount() {
    try { await api.deleteMe(); window.location.assign("/"); } catch (e) { setProblem((e as Error).message); }
  }
  return (
    <section className="panel">
      <div className="ph"><div><div className="eyebrow">Your data</div><h2>Account</h2></div></div>
      <div className="pb insp">
        <p className="note">Runs and their graphs are dropped when a run closes. <a className="linkish" href="/privacy">What Groundwork keeps, and where your data goes</a>.</p>
        {deleting
          ? (
            <p className="note">
              Delete your account? Your keys, apps, teams, runs and cache are removed, and Google's access is revoked.{" "}
              <button className="btn danger" onClick={() => void deleteAccount()}>Yes, delete it all</button>{" "}
              <button className="linkish" onClick={() => setDeleting(false)}>Keep it</button>
            </p>
          )
          : <div><button className="btn danger" onClick={() => setDeleting(true)}>Delete my account…</button></div>}
        {problem && <p className="err">{problem}</p>}
      </div>
    </section>
  );
}
