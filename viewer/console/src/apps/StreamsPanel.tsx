import { useEffect, useId, useState } from "react";
import { api } from "../api";
import { c } from "../css";
import type { PublicStream, StreamEntry, StreamPeek } from "../types";

interface Props {
  streams: StreamEntry[];
  pace: number | null | undefined; // seconds between two polls (unset: 30 with streams)
  polls: number | undefined; // how many polls a run lasts (unset: 24)
  onChange: (patch: { streams?: StreamEntry[]; pace?: number | null; polls?: number }) => void;
}

const nameOf = (e: StreamEntry) => String(e.name ?? e.preset ?? "");
const HOW: Record<string, string> = { poll: "a page, read every", websocket: "a websocket", events: "an event stream" };

/** Live data on the open internet that this team reads besides its apps: no account, no key.
 * Each stream is one of the public ones (packs/apps/public_streams.py), with filters of yours, or
 * one you describe yourself; Peek reads it for a few seconds and shows what the team would get. */
export function StreamsPanel({ streams, pace, polls, onChange }: Props) {
  const [topics, setTopics] = useState<{ topic: string; streams: PublicStream[] }[]>([]);
  const [peeks, setPeeks] = useState<Record<string, StreamPeek>>({});
  const [peeking, setPeeking] = useState<string | null>(null);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    api.streams().then((r) => setTopics(r.topics)).catch((e: Error) => setProblem(e.message));
  }, []);

  const known: Record<string, PublicStream> = Object.fromEntries(topics.flatMap((t) => t.streams).map((s) => [s.name, s]));

  async function peek(key: string, entry: StreamEntry) {
    setPeeking(key);
    try {
      const result = await api.peekStream(entry);
      setPeeks((p) => ({ ...p, [key]: result }));
    } catch (e) {
      setPeeks((p) => ({ ...p, [key]: { received: 0, kept: 0, error: (e as Error).message, items: [] } }));
    } finally {
      setPeeking(null);
    }
  }

  function change(name: string, patch: StreamEntry) {
    onChange({ streams: streams.map((s) => (nameOf(s) === name ? { ...s, ...patch } : s)) });
  }

  const seconds = pace ?? 30;
  const count = polls ?? 24;
  return (
    <section className="panel">
      <div className="ph">
        <div><div className="eyebrow">Step 2 · {streams.length} {streams.length === 1 ? "stream" : "streams"} · public data, no account needed</div><h2>Live data</h2></div>
      </div>
      <div className="pb insp">
        <p className="note">A stream is data anyone can read: quakes, weather alerts, status pages, posts, edits. Its items reach your agents like mail does, through the router to whoever looks after what they are about. An agency's own record (marked <i>trusted</i>) is evidence. A post or an edit is a claim from someone who can be caught lying.</p>
        {streams.length === 0 && <p className="none">No streams: this team reads only its apps. Add one below.</p>}
        {streams.map((entry) => {
          const name = nameOf(entry);
          return (
            <StreamCard
              key={name}
              entry={entry}
              preset={known[String(entry.preset ?? "")]}
              peek={peeks[name]}
              peeking={peeking === name}
              onPeek={() => void peek(name, entry)}
              onChange={(patch) => change(name, patch)}
              onRemove={() => onChange({ streams: streams.filter((s) => nameOf(s) !== name) })}
            />
          );
        })}
        {streams.length > 0 && (
          <div className="row2 pace">
            <label>Read every (seconds)<input type="number" min={5} value={seconds} onChange={(e) => onChange({ pace: Number(e.target.value) || null })} /></label>
            <label>For this many polls<input type="number" min={1} value={count} onChange={(e) => onChange({ polls: Number(e.target.value) || 24 })} /></label>
            <small className="muted">A run watches for about {Math.round((seconds * count) / 60)} minutes. Each item a stream brings is read by the model once.</small>
          </div>
        )}
        <AddStream
          topics={topics}
          taken={streams.map(nameOf)}
          peek={peeks[""]}
          peeking={peeking === ""}
          onPeek={(entry) => void peek("", entry)}
          onAdd={(entry) => onChange({ streams: [...streams, entry] })}
        />
        {problem && <p className="err">{problem}</p>}
      </div>
    </section>
  );
}

// ---- one stream ---------------------------------------------------------------------------------

function StreamCard({ entry, preset, peek, peeking, onPeek, onChange, onRemove }: {
  entry: StreamEntry;
  preset: PublicStream | undefined; // the public stream it is made from, if it is one
  peek: StreamPeek | undefined;
  peeking: boolean;
  onPeek: () => void;
  onChange: (patch: StreamEntry) => void;
  onRemove: () => void;
}) {
  const name = nameOf(entry);
  const kind = String(entry.kind ?? preset?.kind ?? "poll");
  const every = Number(entry.every ?? preset?.every ?? 60);
  const trusted = Boolean(entry.trusted ?? preset?.trusted);
  const keep = (entry.keep as Record<string, string> | undefined) ?? {};
  const drop = (entry.drop as Record<string, string> | undefined) ?? {};
  const fields = [...new Set([...(preset?.fields ?? []), preset?.title ?? "", ...((entry.fields as string[] | undefined) ?? [])])]
    .map((f) => f.split("|")[0]!)
    .filter(Boolean);
  return (
    <div className="conn">
      <div className="conn-h">
        <b>{name}</b>
        <span className="muted">{preset?.label ?? String(entry.url ?? "")}</span>
        <span className="tag">{HOW[kind]}{kind === "poll" ? ` ${every} s` : ""}</span>
        {trusted && <span className="tag" style={c("var(--ok)")}>trusted</span>}
        <span className="grow" />
        <button className="btn" disabled={peeking} onClick={onPeek}>{peeking ? "Reading…" : "Peek"}</button>
        <button className="btn" onClick={onRemove} aria-label={`Remove ${name}`}>Remove</button>
      </div>
      {preset?.about && <p className="note">{preset.about}</p>}
      {preset && Object.keys(preset.keep).length > 0 && (
        <p className="note">Always kept only: {Object.entries(preset.keep).map(([f, r]) => <code key={f}>{f} ~ {r}</code>)}</p>
      )}
      <Filters label="Keep only items where" rules={keep} fields={fields} onChange={(rules) => onChange({ keep: rules })} />
      <Filters label="Leave out items where" rules={drop} fields={fields} onChange={(rules) => onChange({ drop: rules })} />
      <label className="most">At most this many items a poll (the newest)<input type="number" min={1} max={50} value={Number(entry.most ?? preset?.most ?? 5)} onChange={(e) => onChange({ most: Number(e.target.value) || 5 })} /></label>
      {peek && <PeekResult peek={peek} />}
    </div>
  );
}

/** Rules of a filter: a field (a path in an item) and a regex its text must match. */
function Filters({ label, rules, fields, onChange }: {
  label: string;
  rules: Record<string, string>;
  fields: string[];
  onChange: (rules: Record<string, string>) => void;
}) {
  const [field, setField] = useState("");
  const [regex, setRegex] = useState("");
  const listId = useId();
  function add() {
    if (!field.trim() || !regex.trim()) return;
    onChange({ ...rules, [field.trim()]: regex.trim() });
    setField(""); setRegex("");
  }
  return (
    <div className="filters">
      <div className="sub">{label}</div>
      {Object.entries(rules).map(([f, r]) => (
        <div key={f} className="kinds">
          <code>{f}</code><span className="muted">matches</span><code>{r}</code>
          <button className="chip" onClick={() => onChange(Object.fromEntries(Object.entries(rules).filter(([k]) => k !== f)))}>remove</button>
        </div>
      ))}
      <div className="row2">
        <input list={listId} value={field} onChange={(e) => setField(e.target.value)} placeholder="field, like title" aria-label="Field" />
        <datalist id={listId}>{fields.map((f) => <option key={f} value={f} />)}</datalist>
        <input value={regex} onChange={(e) => setRegex(e.target.value)} placeholder="(?i)taiwan|hualien" aria-label="Regex" />
        <button className="btn" disabled={!field.trim() || !regex.trim()} onClick={add}>Add</button>
      </div>
    </div>
  );
}

function PeekResult({ peek }: { peek: StreamPeek }) {
  return (
    <div className="peek">
      <small className="muted">{peek.received} came · {peek.kept} matched{peek.items.length ? ` · the team would read ${peek.items.length}:` : ""}</small>
      {peek.error && <p className="err">{peek.error}</p>}
      {!peek.error && peek.items.length === 0 && <p className="none">Nothing matched while it was read. A quiet stream may need longer, or a looser filter.</p>}
      <ul className="bl">
        {peek.items.map((item, i) => (
          <li key={i} className="peek-item">
            <span><b>{item.subject}</b> <small className="muted">from {item.from}</small></span>
            <pre>{item.body}</pre>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---- adding one ---------------------------------------------------------------------------------

function AddStream({ topics, taken, peek, peeking, onPeek, onAdd }: {
  topics: { topic: string; streams: PublicStream[] }[];
  taken: string[];
  peek: StreamPeek | undefined;
  peeking: boolean;
  onPeek: (entry: StreamEntry) => void;
  onAdd: (entry: StreamEntry) => void;
}) {
  const [custom, setCustom] = useState(false);
  const [draft, setDraft] = useState({
    name: "", kind: "poll", url: "", format: "json", every: "60", items: "", id: "", sender: "", title: "", fields: "", hello: "", trusted: false,
  });
  const [problem, setProblem] = useState("");
  const set = (patch: Partial<typeof draft>) => setDraft((d) => ({ ...d, ...patch }));

  /** The stream the form describes, or a reason it does not describe one yet. */
  function entry(): StreamEntry | string {
    if (!/^[a-z0-9][a-z0-9-]*$/.test(draft.name)) return "name: lowercase letters, digits and -";
    if (taken.includes(draft.name)) return `this team already has a stream named ${draft.name}`;
    const found: StreamEntry = { name: draft.name, kind: draft.kind, url: draft.url.trim() };
    if (draft.kind === "poll") { found.format = draft.format; found.every = Number(draft.every) || 60; }
    for (const key of ["items", "id", "sender", "title"] as const) if (draft[key].trim()) found[key] = draft[key].trim();
    const fields = draft.fields.split("\n").map((f) => f.trim()).filter(Boolean);
    if (fields.length) found.fields = fields;
    if (draft.kind === "websocket" && draft.hello.trim()) {
      try { found.hello = JSON.parse(draft.hello); } catch { return "the message sent on connecting must be JSON"; }
    }
    if (draft.trusted) found.trusted = true;
    return found;
  }

  function act(then: (e: StreamEntry) => void) {
    const found = entry();
    if (typeof found === "string") return setProblem(found);
    setProblem("");
    then(found);
  }

  return (
    <div className="add-app">
      <div className="eyebrow">Add a stream</div>
      {topics.map((t) => (
        <div key={t.topic} className="topic">
          <div className="sub">{t.topic}</div>
          <div className="kinds">
            {t.streams.map((s) => (
              <button key={s.name} className="btn" disabled={taken.includes(s.name)} title={s.about} onClick={() => onAdd({ preset: s.name })}>+ {s.label}</button>
            ))}
          </div>
        </div>
      ))}
      <div><button className="btn" aria-pressed={custom} onClick={() => setCustom(!custom)}>+ A stream of your own…</button></div>
      {custom && (
        <div className="insp custom">
          <label>Name (its node is name-feed)<input value={draft.name} onChange={(e) => set({ name: e.target.value })} placeholder="my-alerts" /></label>
          <div className="seg" role="group" aria-label="What it is">
            <button aria-pressed={draft.kind === "poll"} onClick={() => set({ kind: "poll" })}>A page to read again</button>
            <button aria-pressed={draft.kind === "websocket"} onClick={() => set({ kind: "websocket" })}>A websocket</button>
            <button aria-pressed={draft.kind === "events"} onClick={() => set({ kind: "events" })}>An event stream</button>
          </div>
          <label>URL<input value={draft.url} onChange={(e) => set({ url: e.target.value })} placeholder={draft.kind === "websocket" ? "wss://example.org/stream" : "https://example.org/alerts.json"} /></label>
          {draft.kind === "poll" && (
            <div className="row2">
              <div className="seg" role="group" aria-label="Format">
                <button aria-pressed={draft.format === "json"} onClick={() => set({ format: "json" })}>JSON</button>
                <button aria-pressed={draft.format === "rss"} onClick={() => set({ format: "rss" })}>RSS or Atom</button>
              </div>
              <label>Every (seconds, 10 or more)<input type="number" min={10} value={draft.every} onChange={(e) => set({ every: e.target.value })} /></label>
            </div>
          )}
          {draft.kind === "websocket" && (
            <label>Sent once connected, as JSON (a subscription; may be empty)<textarea rows={2} value={draft.hello} onChange={(e) => set({ hello: e.target.value })} placeholder='{"type": "subscribe", "channels": ["alerts"]}' /></label>
          )}
          <p className="note">Paths say where things are in a page or a message, with dots: <code>features</code>, <code>properties.title</code>, <code>items.0.name</code>. Peek shows what comes out.</p>
          <div className="row2">
            <label>Where the items are listed<input value={draft.items} onChange={(e) => set({ items: e.target.value })} placeholder={draft.format === "rss" ? "(found by itself)" : "features"} disabled={draft.kind === "poll" && draft.format === "rss"} /></label>
            <label>What names each item<input value={draft.id} onChange={(e) => set({ id: e.target.value })} placeholder="id" /></label>
          </div>
          <div className="row2">
            <label>Its title<input value={draft.title} onChange={(e) => set({ title: e.target.value })} placeholder="properties.title" /></label>
            <label>Who it is from (blank: the stream)<input value={draft.sender} onChange={(e) => set({ sender: e.target.value })} placeholder="author" /></label>
          </div>
          <label>What the team reads of each, one path per line (blank: all of it; path|ms or path|s for an epoch time)
            <textarea rows={3} value={draft.fields} onChange={(e) => set({ fields: e.target.value })} placeholder={"properties.title\nproperties.time|ms"} />
          </label>
          <label className="check"><input type="checkbox" checked={draft.trusted} onChange={(e) => set({ trusted: e.target.checked })} /> It is a system of record (an agency's own data): its items are evidence, not claims to check</label>
          <div className="row-btns">
            <button className="btn" disabled={peeking} onClick={() => act(onPeek)}>{peeking ? "Reading…" : "Peek"}</button>
            <button className="btn primary" onClick={() => act((e) => { onAdd(e); setCustom(false); })}>Add it</button>
          </div>
          {problem && <p className="err">{problem}</p>}
          {peek && <PeekResult peek={peek} />}
        </div>
      )}
    </div>
  );
}
