import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type RunOptions } from "../api";
import { c } from "../css";
import { Graph } from "../Graph";
import { KIND_COLOUR, KIND_LABEL, layout, type Positions } from "../layout";
import type { Catalogue, LinkKind, NodeKind, NodeSpec, PackInfo, Settings, TeamSpec, Template } from "../types";
import { Inspector } from "./Inspector";

interface Props {
  onRun: (pack: string, team: TeamSpec, name: string, options: RunOptions) => Promise<void>;
}

const LINK_KINDS: LinkKind[] = ["talks_to", "feeds", "watches"];
type Tab = "Teams" | "Add" | "Edit" | "Team";
const DRAFT = "graph-agent:draft";

interface Draft { template: Template; team: TeamSpec; positions: Positions }

function loadDraft(): Draft | null {
  try {
    const raw = localStorage.getItem(DRAFT);
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

function saveDraft(draft: Draft) {
  try {
    localStorage.setItem(DRAFT, JSON.stringify(draft));
  } catch {
    /* storage may be unavailable: the draft is only a convenience */
  }
}

/** The canvas, laid out like the Fire game: the team as a graph on the left, and a separate side
 * screen to pick a ready-made team, add nodes, edit the selected node or link, and set the team. */
export function BuildView({ onRun }: Props) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [chosen, setChosen] = useState<Template | null>(null);
  const [team, setTeam] = useState<TeamSpec | null>(null);
  const [catalogue, setCatalogue] = useState<Catalogue | null>(null);
  const [positions, setPositions] = useState<Positions>({});
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedLink, setSelectedLink] = useState<number | null>(null);
  const [linkKind, setLinkKind] = useState<LinkKind | null>(null);
  const [linkFrom, setLinkFrom] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("Teams");
  const [problems, setProblems] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [options, setOptions] = useState<RunOptions>({ model: "stand-in", store: "memory", options: {} });

  const choose = useCallback(async (template: Template, restore?: Draft) => {
    try {
      const [loaded, cat] = await Promise.all([
        restore ? Promise.resolve(restore.team) : api.template(template.pack, template.name),
        api.catalogue(template.pack),
      ]);
      setChosen(template);
      setTeam(loaded);
      setCatalogue(cat);
      // the run options show what the team says it will do: a real-accounts team never looks "run at once"
      const real = Boolean(loaded.settings?.extra?.real);
      setOptions((o) => ({
        ...o,
        model: real ? "claude-haiku-5-5" : o.model,
        options: { ...o.options, approvals: loaded.settings?.approvals ?? "auto", extraction: real ? "model" : "gold" },
      }));
      setPositions(restore?.positions ?? layout(loaded));
      setSelected(null);
      setSelectedLink(null);
      setProblems([]);
    } catch (e) {
      setProblems([(e as Error).message]);
    }
  }, []);

  useEffect(() => {
    api.packs().then(setPacks).catch(() => setPacks([]));
    api.templates().then((list) => {
      setTemplates(list);
      const draft = loadDraft();
      if (draft) return void choose(draft.template, draft);
      const first = list.find((t) => t.name === "travel") ?? list[0];
      if (first) void choose(first);
    }).catch((e: Error) => setProblems([e.message]));
  }, [choose]);

  // keep the work in progress, so a reload does not lose it
  useEffect(() => {
    if (team && chosen) saveDraft({ template: chosen, team, positions });
  }, [team, chosen, positions]);

  const kinds = useMemo(() => {
    const out: Record<string, NodeKind> = {};
    for (const n of catalogue?.nodes ?? []) out[n.type] = n.kind;
    return out;
  }, [catalogue]);

  const update = useCallback((next: TeamSpec) => { setTeam(next); setProblems([]); }, []);

  const removeNode = useCallback((id: string) => {
    if (!team) return;
    update({ ...team, nodes: team.nodes.filter((n) => n.id !== id), links: team.links.filter((l) => l.src !== id && l.dst !== id) });
    setSelected(null);
  }, [team, update]);

  const removeLink = useCallback((i: number) => {
    if (!team) return;
    update({ ...team, links: team.links.filter((_, k) => k !== i) });
    setSelectedLink(null);
  }, [team, update]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "Escape") { setLinkKind(null); setLinkFrom(null); setSelected(null); setSelectedLink(null); }
      if (e.key === "Delete" || e.key === "Backspace") {
        if (selected) removeNode(selected);
        else if (selectedLink !== null) removeLink(selectedLink);
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [selected, selectedLink, removeNode, removeLink]);

  if (!team || !catalogue || !chosen) {
    return <p className="none pad">{problems[0] ?? "Loading the ready-made teams…"}</p>;
  }

  const node = team.nodes.find((n) => n.id === selected) ?? null;
  const link = selectedLink !== null ? team.links[selectedLink] ?? null : null;

  function addNode(type: string) {
    if (!team) return;
    const base = type.split(".").pop() ?? type;
    let i = 1;
    while (team.nodes.some((n) => n.id === `${base}-${i}`)) i++;
    const id = `${base}-${i}`;
    const spec: NodeSpec = { id, type, label: `New ${base}`, role: "", goals: "", triggers: [], tools: [], config: {} };
    if (type === "agent") spec.triggers = [{ on: "item" }, { on: "message" }, { on: "change" }];
    if (type === "responder") spec.triggers = [{ on: "message" }, { on: "change" }, { on: "approval" }];
    if (type === "stream") spec.config = { feed: "", when: "start" };
    update({ ...team, nodes: [...team.nodes, spec] });
    const k = team.nodes.length;
    setPositions({ ...positions, [id]: [420 + ((k * 97) % 360), 110 + ((k * 151) % 420)] });
    setSelected(id);
    setTab("Edit");
  }

  function blank() {
    if (!chosen) return;
    setTeam({ name: "My team", pack: chosen.pack, description: "", settings: { ticks: 14, quarantine: "team" }, nodes: [], links: [] });
    setPositions({});
    setSelected(null);
    setSelectedLink(null);
    setTab("Add");
  }

  function pick(id: string | null) {
    if (!team) return;
    setSelectedLink(null);
    if (linkKind && id) {
      if (!linkFrom) { setLinkFrom(id); return; }
      if (linkFrom !== id) {
        const exists = team.links.some((l) => l.kind === linkKind
          && ((l.src === linkFrom && l.dst === id) || (linkKind === "talks_to" && l.src === id && l.dst === linkFrom)));
        if (!exists) update({ ...team, links: [...team.links, { kind: linkKind, src: linkFrom, dst: id }] });
      }
      setLinkFrom(null);
      return;
    }
    setSelected(id);
    if (id) setTab("Edit");
  }

  function withPositions(): TeamSpec {
    return { ...team!, nodes: team!.nodes.map((n) => ({ ...n, position: positions[n.id] ?? n.position ?? null })) };
  }

  async function run() {
    const ready = withPositions();
    setBusy(true);
    try {
      const check = await api.validate(ready);
      if (!check.ok) { setProblems(check.errors); return; }
      await onRun(chosen!.pack, ready, chosen!.name, options);
    } catch (e) {
      setProblems([(e as Error).message]);
    } finally {
      setBusy(false);
    }
  }

  function download() {
    const blob = new Blob([JSON.stringify(withPositions(), null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${team!.name.replace(/\W+/g, "-").toLowerCase() || "team"}.team.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function upload(file: File) {
    try {
      const loaded = JSON.parse(await file.text()) as TeamSpec;
      const pack = loaded.pack || "life";
      setCatalogue(await api.catalogue(pack));
      setChosen({ pack, name: loaded.name, title: loaded.name, description: loaded.description ?? "" });
      setTeam(loaded);
      setPositions(layout(loaded));
    } catch (e) {
      setProblems([`not a team file: ${(e as Error).message}`]);
    }
  }

  const pack = packs.find((p) => p.name === chosen.pack);
  const counts = team.nodes.reduce<Record<string, number>>((acc, n) => {
    const k = n.type === "responder" ? "responder" : kinds[n.type] ?? "code";
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});
  const heading: Record<Tab, [string, string]> = {
    Teams: ["Load a pack", "Ready-made teams"],
    Add: ["The node catalogue", "Add a node"],
    Edit: [node ? node.type : link ? "a link" : "nothing selected", node ? node.label || node.id : link ? `${link.src} → ${link.dst}` : "Inspector"],
    Team: ["How the team runs", "Team settings"],
  };

  return (
    <div className="buildview">
      <section className="tl">
        <div className="tl-row">
          <div className="title">
            <div className="eyebrow">{pack?.title ?? chosen.pack} · {team.nodes.length} nodes · {team.links.length} links</div>
            <h2>{team.name}</h2>
          </div>
          <span className="sep" />
          <label className="opt">Model
            <select value={options.model} onChange={(e) => setOptions({ ...options, model: e.target.value })}>
              <option value="stand-in">Stand-in (free, scripted)</option>
              <option value="claude-haiku-5-5">Claude Haiku 5.5 (cached)</option>
            </select>
          </label>
          <label className="opt">Store
            <select value={options.store} onChange={(e) => setOptions({ ...options, store: e.target.value })}>
              <option value="memory">In memory</option>
              <option value="falkor">FalkorDB (kept)</option>
            </select>
          </label>
          {pack?.options.map((o) => (
            <label key={o.key} className="opt">{o.label}
              <select value={options.options[o.key] ?? o.choices[0]?.value}
                onChange={(e) => setOptions({ ...options, options: { ...options.options, [o.key]: e.target.value } })}>
                {o.choices.map((ch) => <option key={ch.value} value={ch.value}>{ch.label}</option>)}
              </select>
            </label>
          ))}
          <button className="btn primary big" disabled={busy || !team.nodes.length} onClick={() => void run()}>
            {busy ? "Starting…" : "Run this team ⏵"}
          </button>
        </div>
        {problems.length > 0 && <ul className="problems">{problems.map((x, i) => <li key={i}>{x}</li>)}</ul>}
      </section>

      <div className="main">
        <section className="panel">
          <div className="ph">
            <div>
              <div className="eyebrow">Drag to arrange · click to edit · Delete removes</div>
              <h2>Team canvas</h2>
            </div>
            <div className="tools">
              <span className="eyebrow">Link</span>
              <div className="seg">
                {LINK_KINDS.map((k) => (
                  <button key={k} aria-pressed={linkKind === k} title={catalogue.links[k]}
                    onClick={() => { setLinkKind(linkKind === k ? null : k); setLinkFrom(null); }}>
                    {k.replace("_", " ")}
                  </button>
                ))}
              </div>
              <button className="btn" onClick={() => setPositions(layout(team, true))} title="Arrange the nodes again">Tidy</button>
            </div>
          </div>
          {linkKind && (
            <p className="hintbar">
              {linkFrom ? <>Now click the node to link <b>{linkFrom}</b> to.</> : <>Click the first node of the <b>{linkKind.replace("_", " ")}</b> link.</>}{" "}
              <button className="linkish" onClick={() => { setLinkKind(null); setLinkFrom(null); }}>Done</button>
            </p>
          )}
          <div className="net canvas">
            <Graph
              team={team}
              positions={positions}
              kinds={kinds}
              selected={selected}
              onSelect={pick}
              editable
              onMove={(id, at) => setPositions((p) => ({ ...p, [id]: at }))}
              linkFrom={linkFrom}
              selectedLink={selectedLink}
              onSelectLink={(i) => { setSelectedLink(i); setSelected(null); if (i !== null) setTab("Edit"); }}
            />
            {team.nodes.length === 0 && (
              <div className="empty">
                <h3>An empty team</h3>
                <p>Add nodes from the side screen: a stream to read from, a router, agents that own what items are about, a responder to act, a checker.</p>
              </div>
            )}
            <div className="counter kinds-count">
              {(["model", "responder", "source", "code"] as const).map((k) => (
                <span key={k} className="kcount"><i style={c(KIND_COLOUR[k])} />{counts[k] ?? 0} {KIND_LABEL[k]}{(counts[k] ?? 0) === 1 ? "" : "s"}</span>
              ))}
            </div>
          </div>
          <div className="legend">
            <span><i className="o" style={c("var(--ink)")} />node · the dot is its kind</span>
            <span><i className="dash" style={c("var(--water)")} />feeds</span>
            <span><i style={c("var(--line)")} />talks to</span>
            <span><i className="dot" style={c("var(--gold)")} />watches</span>
            <span><i className="o d" style={c("var(--lie)")} />scripted</span>
          </div>
        </section>

        <section className="panel side">
          <div className="ph">
            <div>
              <div className="eyebrow">{heading[tab][0]}</div>
              <h2>{heading[tab][1]}</h2>
            </div>
          </div>
          <div className="pb">
            <div className="seg tabs" role="tablist">
              {(["Teams", "Add", "Edit", "Team"] as Tab[]).map((t) => (
                <button key={t} role="tab" aria-pressed={tab === t} onClick={() => setTab(t)}>{t}</button>
              ))}
            </div>
            <div className="tabbody">
              {tab === "Teams" && (
                <div className="list">
                  {packs.map((p) => (
                    <div key={p.name} className="packgroup">
                      <div className="eyebrow">{p.title}</div>
                      {templates.filter((t) => t.pack === p.name).map((t) => (
                        <button key={`${t.pack}/${t.name}`} className={`tpl ${chosen.name === t.name && chosen.pack === t.pack ? "on" : ""}`} onClick={() => void choose(t)}>
                          <b>{t.title}</b>
                          <small>{t.description}</small>
                        </button>
                      ))}
                    </div>
                  ))}
                  <div className="row-btns">
                    <button className="btn" onClick={blank}>Blank {chosen.pack} team</button>
                    <button className="btn" onClick={download}>Export</button>
                    <label className="btn file">Import<input type="file" accept=".json" onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); }} /></label>
                  </div>
                </div>
              )}
              {tab === "Add" && (
                <div className="list">
                  {catalogue.nodes.map((n) => {
                    const k = n.type === "responder" ? "responder" : n.kind;
                    return (
                      <button key={n.type} className="nodetype" onClick={() => addNode(n.type)} title={n.description}>
                        <i className="k" style={c(KIND_COLOUR[k])} />
                        <span><b>{n.type}</b> <small className="kind">{KIND_LABEL[k]}</small><small>{n.description}</small></span>
                      </button>
                    );
                  })}
                </div>
              )}
              {tab === "Edit" && node && (
                <Inspector
                  key={node.id}
                  node={node}
                  team={team}
                  catalogue={catalogue}
                  onChange={(next) => update({ ...team, nodes: team.nodes.map((n) => (n.id === node.id ? next : n)) })}
                  onLinks={(links) => update({ ...team, links })}
                  onDelete={() => removeNode(node.id)}
                />
              )}
              {tab === "Edit" && !node && link && (
                <div className="insp">
                  <p className="note">{catalogue.links[link.kind]}</p>
                  <label>Kind
                    <select value={link.kind} onChange={(e) => update({ ...team, links: team.links.map((l, i) => (i === selectedLink ? { ...l, kind: e.target.value as LinkKind } : l)) })}>
                      {LINK_KINDS.map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}
                    </select>
                  </label>
                  <button className="btn danger" onClick={() => removeLink(selectedLink!)}>Delete this link</button>
                </div>
              )}
              {tab === "Edit" && !node && !link && (
                <div className="insp">
                  <p className="note">
                    Click a node to edit its role, what wakes it and which tools it may use; click a line to change or delete a link.
                    Every node's memory is the shared graph: it never sees its own chat history. Items are linked to the things they are
                    about, and the nodes that <i>own</i> those things wake.
                  </p>
                </div>
              )}
              {tab === "Team" && <TeamSettings team={team} onChange={update} />}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}

function TeamSettings({ team, onChange }: { team: TeamSpec; onChange: (t: TeamSpec) => void }) {
  const s: Settings = team.settings ?? {};
  const set = (patch: Partial<Settings>) => onChange({ ...team, settings: { ...s, ...patch } });
  return (
    <div className="insp">
      <label>Name<input value={team.name} onChange={(e) => onChange({ ...team, name: e.target.value })} /></label>
      <label>Description<textarea rows={3} value={team.description ?? ""} onChange={(e) => onChange({ ...team, description: e.target.value })} /></label>
      <fieldset>
        <legend>Clock and budget</legend>
        <label>Ticks to run<input type="number" min={1} value={s.ticks ?? 14} onChange={(e) => set({ ticks: Number(e.target.value) })} /></label>
        <label>Context budget per turn (tokens)<input type="number" min={500} step={500} value={s.budget ?? 4000} onChange={(e) => set({ budget: Number(e.target.value) })} /></label>
        <label>Model rounds per turn<input type="number" min={1} max={20} value={s.max_steps ?? 6} onChange={(e) => set({ max_steps: Number(e.target.value) })} /></label>
      </fieldset>
      <fieldset>
        <legend>Trust</legend>
        <label>A sender one node catches lying
          <select value={s.quarantine ?? "self"} onChange={(e) => set({ quarantine: e.target.value as Settings["quarantine"] })}>
            <option value="team">is blocked for the whole team</option>
            <option value="self">is distrusted by that node only</option>
          </select>
        </label>
        <label>When evidence refutes a claim, blame
          <select value={s.blame ?? "direct_teller"} onChange={(e) => set({ blame: e.target.value as Settings["blame"] })}>
            <option value="direct_teller">whoever told it directly</option>
            <option value="first_hop">whoever it started from</option>
            <option value="whole_route">everyone on its route</option>
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={s.repair ?? false} onChange={(e) => set({ repair: e.target.checked })} />
          Trust a node again once the source of the lie it passed on is caught
        </label>
        <label className="check">
          <input type="checkbox" checked={s.trace_provenance ?? false} onChange={(e) => set({ trace_provenance: e.target.checked })} />
          A conclusion drawn from a told claim travels on that claim's route
        </label>
      </fieldset>
      <p className="note">Outward actions (send, pay, book) are set when you run: at once, waiting for you, or recorded only.</p>
    </div>
  );
}
