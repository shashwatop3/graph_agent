import { useEffect, useState } from "react";
import { c } from "../css";
import { LENSES } from "../lenses";
import type { Proposal, RunEvent, SpaceState } from "../types";
import { callText, describe, distrustAt, DROPPED, statusAt } from "./model";

interface Props {
  space: SpaceState;
  events: RunEvent[];
  tick: number;
  onDecide: (id: string, approved: boolean) => void;
  onOpen: (node: string) => void;
}

type Tab = "World" | "Actions" | "Memory" | "Log";

/** The side screen: the state of things, separate from the network, like the Fire game's "Real
 * world" panel. World is the pack's own view; Actions waits on a person and shows what was held;
 * Memory is each node's beliefs at this tick; Log is every event. */
export function Side({ space, events, tick, onDecide, onOpen }: Props) {
  const lens = space.world.lens ? LENSES[space.world.lens] : undefined;
  const pending = space.proposals.filter((p) => p.status === "pending");
  const [tab, setTab] = useState<Tab>(lens ? "World" : "Memory");
  useEffect(() => { if (pending.length) setTab("Actions"); }, [pending.length]);
  const badge: Partial<Record<Tab, number>> = {
    Actions: pending.length || space.proposals.filter((p) => p.status === "held").length,
  };
  const head: Record<Tab, [string, string]> = {
    World: [lens?.eyebrow ?? "", lens?.title ?? "World"],
    Actions: ["Needs a person · cascades", "Actions"],
    Memory: [`Each node's beliefs at ${space.clocks[tick] ?? `tick ${tick}`}`, "Memory"],
    Log: ["Every event, newest first", "What happened"],
  };
  const tabs: Tab[] = lens ? ["World", "Actions", "Memory", "Log"] : ["Actions", "Memory", "Log"];
  return (
    <section className="panel side">
      <div className="ph">
        <div>
          <div className="eyebrow">{head[tab][0]}</div>
          <h2>{head[tab][1]}</h2>
        </div>
        <span className="eyebrow">{space.clocks[tick] ?? `tick ${tick}`}</span>
      </div>
      <div className="pb">
        <div className="seg tabs" role="tablist">
          {tabs.map((t) => (
            <button key={t} role="tab" aria-pressed={tab === t} onClick={() => setTab(t)}>
              {t}{badge[t] ? <span className="badge">{badge[t]}</span> : null}
            </button>
          ))}
        </div>
        <div className="tabbody">
          {tab === "World" && lens && <lens.Body space={space} />}
          {tab === "Actions" && <Actions space={space} onDecide={onDecide} />}
          {tab === "Memory" && <Memory space={space} events={events} tick={tick} onOpen={onOpen} />}
          {tab === "Log" && <Log space={space} events={events} tick={tick} />}
        </div>
      </div>
    </section>
  );
}

const STATUS_COLOUR: Record<string, string> = {
  done: "var(--ok)", pending: "var(--accent)", held: "var(--gold)", reviewed: "var(--gold)",
  shadow: "var(--muted)", rejected: "var(--stale)", failed: "var(--stale)", approved: "var(--accent)",
};

function Actions({ space, onDecide }: { space: SpaceState; onDecide: (id: string, approved: boolean) => void }) {
  const group = (statuses: string[]) => space.proposals.filter((p) => statuses.includes(p.status));
  const pending = group(["pending"]);
  const held = group(["held", "reviewed"]);
  const rest = group(["done", "shadow", "rejected", "failed", "approved"]);
  if (!space.proposals.length) return <p className="none">No outward actions yet. Nodes propose them with the beliefs they rest on; if those change, the action is held.</p>;
  const row = (p: Proposal, buttons = false) => (
    <li key={p.id} className={`act ${p.status}`}>
      <span>
        <b>{p.node}</b> · {p.status === "shadow" ? "would do " : ""}{callText(p)}
        <small>
          {p.status === "held" || p.status === "reviewed" ? p.note : p.result || `rests on ${p.basis.join(", ") || "nothing"}`}
        </small>
      </span>
      {buttons ? (
        <span className="pair">
          <button className="btn ok" onClick={() => onDecide(p.id, true)}>Approve</button>
          <button className="btn" onClick={() => onDecide(p.id, false)}>Reject</button>
        </span>
      ) : (
        <span className="tag" style={c(STATUS_COLOUR[p.status] ?? "var(--muted)")}>{p.status}</span>
      )}
    </li>
  );
  return (
    <>
      {pending.length > 0 && <><div className="eyebrow">Waiting for you · {pending.length}</div><ul className="bl">{pending.map((p) => row(p, true))}</ul></>}
      {held.length > 0 && <><div className="eyebrow">Held: what they rested on changed · {held.length}</div><ul className="bl">{held.map((p) => row(p))}</ul></>}
      {rest.length > 0 && <><div className="eyebrow">Done, recorded or refused · {rest.length}</div><ul className="bl">{[...rest].reverse().map((p) => row(p))}</ul></>}
    </>
  );
}

function Memory({ space, events, tick, onOpen }: { space: SpaceState; events: RunEvent[]; tick: number; onOpen: (n: string) => void }) {
  const rows = space.nodes
    .filter((n) => n.id in space.beliefs)
    .map((n) => {
      const statuses = (space.beliefs[n.id] ?? []).map((b) => statusAt(b, tick)).filter((s): s is string => s !== null);
      const distrusts = distrustAt(events, tick).filter((c) => c.viewer === n.id).length;
      return {
        node: n,
        live: statuses.filter((s) => s === "active").length,
        suspect: statuses.filter((s) => s === "suspect").length,
        dropped: statuses.filter((s) => DROPPED.has(s)).length,
        distrusts,
        turn: events.some((e) => e.kind === "turn" && e.node === n.id && e.tick === tick),
      };
    });
  const max = Math.max(1, ...rows.map((r) => r.live + r.suspect + r.dropped));
  return (
    <>
      <table className="mem">
        <thead>
          <tr><th>node</th><th>beliefs</th><th>live</th><th>suspect</th><th>dropped</th><th>distrusts</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.node.id} onClick={() => onOpen(r.node.id)} className={r.turn ? "on" : ""}>
              <td><b>{r.node.label}</b>{r.turn && <i className="dot" title="took a turn" />}</td>
              <td>
                <span className="bar">
                  <i style={c("var(--accent)", { width: `${(r.live / max) * 100}%` })} />
                  <i style={c("var(--fire)", { width: `${(r.suspect / max) * 100}%` })} />
                  <i style={c("var(--stale)", { width: `${(r.dropped / max) * 100}%` })} />
                </span>
              </td>
              <td>{r.live}</td><td>{r.suspect}</td><td>{r.dropped}</td><td>{r.distrusts || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="note">
        A node's memory is its part of the graph: what it was told (with the route), saw for itself, or worked out. A dropped belief lost
        all its support; a suspect one rests on something that changed. Click a row to open the node.
      </p>
    </>
  );
}

const KINDS = ["item", "message", "turn", "change", "exposure", "reinstatement", "proposal", "action", "held", "extract"];

function Log({ space, events, tick }: { space: SpaceState; events: RunEvent[]; tick: number }) {
  const [on, setOn] = useState<Set<string>>(new Set(["item", "message", "change", "exposure", "reinstatement", "action", "held"]));
  const shown = events.filter((e) => e.tick <= tick && on.has(e.kind)).slice(-200).reverse();
  return (
    <>
      <div className="kinds">
        {KINDS.map((k) => (
          <label key={k} className="check">
            <input type="checkbox" checked={on.has(k)} onChange={() => { const n = new Set(on); if (n.has(k)) n.delete(k); else n.add(k); setOn(n); }} />{k}
          </label>
        ))}
      </div>
      <ol className="feed">
        {shown.map((e) => (
          <li key={e.seq} className={`ev ${e.kind}`}><span className="t">{space.clocks[e.tick]?.split(" ")[0] ?? e.tick}</span><span>{describe(e, space)}</span></li>
        ))}
      </ol>
    </>
  );
}
