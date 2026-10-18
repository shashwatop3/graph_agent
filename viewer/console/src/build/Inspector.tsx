import { useState } from "react";
import type { Catalogue, LinkSpec, NodeSpec, TeamSpec, Trigger, TriggerKind } from "../types";

interface Props {
  node: NodeSpec;
  team: TeamSpec;
  catalogue: Catalogue;
  onChange: (node: NodeSpec) => void;
  onLinks: (links: LinkSpec[]) => void;
  onDelete: () => void;
}

const MODEL_TYPES = new Set(["agent", "responder"]);

/** Edit one node: who it is, what wakes it, what it may use, what it owns, and its links. */
export function Inspector({ node, team, catalogue, onChange, onLinks, onDelete }: Props) {
  const [owns, setOwns] = useState("");
  const set = (patch: Partial<NodeSpec>) => onChange({ ...node, ...patch });
  const triggers = node.triggers ?? [];
  const has = (kind: TriggerKind) => triggers.find((t) => t.on === kind);
  const isModel = MODEL_TYPES.has(node.type);
  const links = team.links.filter((l) => l.src === node.id || l.dst === node.id);

  function toggleTrigger(kind: TriggerKind) {
    const next: Trigger[] = has(kind) ? triggers.filter((t) => t.on !== kind) : [...triggers, kind === "schedule" ? { on: kind, every: 2, at: 0 } : kind === "due" ? { on: kind, within: 1 } : { on: kind }];
    set({ triggers: next });
  }

  function toggleTool(name: string) {
    const tools = node.tools ?? [];
    set({ tools: tools.includes(name) ? tools.filter((t) => t !== name) : [...tools, name] });
  }

  return (
    <div className="insp">
      <label>Id<input value={node.id} readOnly /></label>
      <label>Label<input value={node.label ?? ""} onChange={(e) => set({ label: e.target.value })} /></label>
      {isModel && (
        <>
          <label>Role<input value={node.role ?? ""} onChange={(e) => set({ role: e.target.value })} placeholder="travel: flights, bookings and the trip" /></label>
          <label>Instructions<textarea rows={6} value={node.goals ?? ""} onChange={(e) => set({ goals: e.target.value })} /></label>
          <fieldset>
            <legend>Wakes on</legend>
            {(Object.keys(catalogue.triggers) as TriggerKind[]).map((kind) => (
              <label key={kind} className="check" title={catalogue.triggers[kind]}>
                <input type="checkbox" checked={!!has(kind)} onChange={() => toggleTrigger(kind)} /> {kind}
                {kind === "schedule" && has(kind) && (
                  <span className="mini"> every <input type="number" min={1} value={has(kind)!.every ?? 1} onChange={(e) => set({ triggers: triggers.map((t) => (t.on === "schedule" ? { ...t, every: Number(e.target.value) } : t)) })} /> ticks</span>
                )}
              </label>
            ))}
          </fieldset>
          {catalogue.tools.length > 0 && (
            <fieldset>
              <legend>Its own tools</legend>
              {catalogue.tools.map((t) => (
                <label key={t.name} className="check" title={t.description}>
                  <input type="checkbox" checked={(node.tools ?? []).includes(t.name)} onChange={() => toggleTool(t.name)} /> {t.name}
                  {t.outward && <span className="tag" style={{ ["--c" as string]: "var(--fire)" }}>outward</span>}
                  {t.checking && <span className="tag" style={{ ["--c" as string]: "var(--ok)" }}>evidence</span>}
                </label>
              ))}
              <p className="note">Outward tools wait for approval when you choose so, and name the beliefs they rest on: if those change, the action is held. Evidence tools record what they find as ground truth.</p>
            </fieldset>
          )}
          <p className="note">Shared graph tools, always: {catalogue.graph_tools.join(", ")}.</p>
        </>
      )}
      {node.type === "stream" && (
        <label>Feed<input value={String(node.config?.feed ?? "")} onChange={(e) => set({ config: { ...node.config, feed: e.target.value } })} /></label>
      )}
      {node.type === "router" && (
        <fieldset>
          <legend>How it reads items</legend>
          <p className="note">A model reads each incoming item and names the things it is about; the router then hands the item to whoever owns them (see Owns on the agents). Items about nothing anyone owns go to the fallback.</p>
          {catalogue.extract_prompt ? (
            <>
              <label>Instructions to the model
                <textarea rows={12} value={String(node.config?.prompt ?? catalogue.extract_prompt)} onChange={(e) => set({ config: { ...node.config, prompt: e.target.value } })} />
              </label>
              <p className="note">The kinds of thing, the known entities and the predicates are added after these instructions automatically. Keep the JSON reply format.</p>
              {node.config?.prompt != null && <button className="btn" onClick={() => { const { prompt: _drop, ...rest } = node.config ?? {}; set({ config: rest }); }}>Reset to the template</button>}
            </>
          ) : (
            <p className="note">This pack reads items with its own built-in instructions.</p>
          )}
        </fieldset>
      )}
      <fieldset>
        <legend>Owns</legend>
        <div className="chips">
          {team.links.filter((l) => l.kind === "owns" && l.src === node.id).map((l) => (
            <button key={l.dst} className="chip" title="remove" onClick={() => onLinks(team.links.filter((x) => x !== l))}>{l.dst} ✕</button>
          ))}
        </div>
        <form onSubmit={(e) => { e.preventDefault(); if (owns.trim()) { onLinks([...team.links, { kind: "owns", src: node.id, dst: owns.trim() }]); setOwns(""); } }}>
          <input value={owns} onChange={(e) => setOwns(e.target.value)} placeholder="type:Flight or an entity id" />
        </form>
      </fieldset>
      <fieldset>
        <legend>Links</legend>
        {links.filter((l) => l.kind !== "owns").length === 0 && <p className="none">None yet.</p>}
        <ul className="bl">
          {links.filter((l) => l.kind !== "owns").map((l, i) => (
            <li key={i}>
              <span>{l.src} <small>{l.kind.replace("_", " ")}</small> {l.dst}</span>
              <button className="linkish" onClick={() => onLinks(team.links.filter((x) => x !== l))}>remove</button>
            </li>
          ))}
        </ul>
      </fieldset>
      <button className="btn danger" onClick={onDelete}>Delete this node</button>
    </div>
  );
}
