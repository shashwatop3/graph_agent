import { type CSSProperties, forwardRef, type ReactNode, useEffect, useRef, useState } from "react";
import { c } from "../css";
import type { BeliefView, RunEvent, SpaceState, Why } from "../types";
import { callText, distrustAt, DROPPED, LIVE, originText, statusAt, str } from "./model";

interface Props {
  style: CSSProperties;
  space: SpaceState;
  events: RunEvent[];
  node: string;
  tick: number;
  belief: string | null; // the belief whose chain is open
  why: Why | null; // its chain, from the server
  onBelief: (id: string | null) => void;
  onOpen: (node: string, belief: string | null) => void;
  onClose: () => void;
}

interface Call { tool: string; arguments: Record<string, unknown>; result: string; text: string }

/** One node at one tick: what it was thinking, the tick's messages as a chat, what it believes
 * (tap one to see why), its actions, and whom it no longer trusts. The Fire game's agent card. */
export const AgentCard = forwardRef<HTMLDivElement, Props>(function AgentCard(p, ref) {
  const { space, events, node, tick } = p;
  const spec = space.team.nodes.find((n) => n.id === node);
  const live = space.nodes.find((n) => n.id === node);
  const turn = events.find((e) => e.kind === "turn" && e.node === node && e.tick === tick);
  const here = events.filter((e) => e.tick === tick);
  const heard = here.filter((e) => e.kind === "message" && e.receiver === node);
  const said = here.filter((e) => e.kind === "message" && e.sender === node);
  const items = here.filter((e) => e.kind === "item" && ((e.to as string[]) ?? []).includes(node));
  const owns = space.team.links.filter((l) => l.kind === "owns" && l.src === node).map((l) => l.dst.replace("type:", ""));
  const distrusts = distrustAt(events, tick).filter((c) => c.viewer === node).map((c) => c.agent);
  const calls = (turn?.calls as Call[] | undefined) ?? [];
  const thought = str(turn?.text) || calls.map((x) => x.text).filter(Boolean).slice(-1)[0] || "";

  return (
    <div className="card in" ref={ref} style={p.style} onClick={(e) => e.stopPropagation()}>
      <div className="card-h">
        <span className="name">{spec?.label || node}</span>
        <span className="tag">{spec?.type}</span>
        {owns.length > 0 && <span className="tag">owns {owns.slice(0, 2).join(", ")}{owns.length > 2 ? "…" : ""}</span>}
        <button className="x" onClick={p.onClose} aria-label="Close">✕</button>
      </div>
      {spec?.role && <p className="role">{spec.role}</p>}

      <div className="sec">
        <div className="eyebrow">Thinking · {space.clocks[tick] ?? `tick ${tick}`}</div>
        {turn ? (
          <Typed key={`${node}|${tick}`} text={thought || (calls.length ? `(no words: it acted through ${calls.length} tool call${calls.length > 1 ? "s" : ""})` : "(no reply)")} />
        ) : (
          <p className="none">
            {live?.kind === "model"
              ? `Did not take a turn at this tick${live.last_turn != null ? `; its last turn was at ${space.clocks[live.last_turn] ?? live.last_turn}` : ""}.`
              : live?.kind === "scripted" ? "Scripted: no model turn." : "Code: it acts on events, without a model."}
          </p>
        )}
        {turn && calls.length > 0 && (
          <details>
            <summary>{calls.length} tool call{calls.length > 1 ? "s" : ""} · {str(turn.tokens_in)} tokens in</summary>
            <ul>
              {calls.map((x, k) => (
                <li key={k} className={x.result.startsWith("error") ? "err" : ""}>
                  {x.tool}({Object.entries(x.arguments).map(([a, v]) => `${a}=${str(v)}`).join(", ")}) → {x.result.slice(0, 220)}
                </li>
              ))}
            </ul>
          </details>
        )}
        {turn && (
          <details>
            <summary>What it read: its whole memory, compiled from the graph</summary>
            <pre className="ctx">{str(turn.context)}</pre>
          </details>
        )}
      </div>

      <div className="sec">
        <div className="eyebrow">Chat · {heard.length + items.length} in, {said.length} out</div>
        <div className="chat">
          <Capped
            k={5}
            items={[
              ...items.map((e) => ["item", e] as const),
              ...heard.map((e) => ["in", e] as const),
              ...said.map((e) => ["out", e] as const),
            ]}
            render={([dir, e], k) => <Bubble key={k} dir={dir} e={e} />}
          />
        </div>
      </div>

      <Beliefs {...p} />

      <Actions space={space} node={node} tick={tick} />

      {distrusts.length > 0 && (
        <div className="sec">
          <div className="eyebrow">Trust</div>
          <p className="none" style={{ color: "var(--stale)" }}>
            Stopped trusting {distrusts.join(", ")}: what they said didn't match the evidence.
          </p>
        </div>
      )}
    </div>
  );
});

function Bubble({ dir, e }: { dir: "in" | "out" | "item"; e: RunEvent }) {
  if (dir === "item") {
    const payload = (e.payload as Record<string, unknown> | undefined) ?? {};
    return (
      <div className="row">
        <span className="who" title={str(e.source)}>{str(e.source).slice(0, 3)}</span>
        <div className="bub item">
          <b>{str(payload.subject) || str(e.item_kind)}</b>
          <small>{str(e.source)} · {str(e.item)}</small>
        </div>
      </div>
    );
  }
  const other = dir === "out" ? str(e.receiver) : str(e.sender);
  const route = (e.route as string[] | undefined) ?? [];
  return (
    <div className={`row ${dir}`}>
      <span className="who" title={other}>{other.slice(0, 3)}</span>
      <div className={`bub ${e.believed ? "" : "false"}`}>
        {dir === "out" && <><b>to {other}</b> · </>}
        {str(e.subject)} {str(e.predicate)} = {str(e.value)}
        {!e.believed && <> <span className="tag" style={c("var(--lie)")}>not believed</span></>}
        <small>{route.length > 1 ? `relayed ${route.join(" → ")}` : "first-hand"}</small>
      </div>
    </div>
  );
}

function Capped<T>({ items, render, k = 3 }: { items: readonly T[]; render: (item: T, key: number) => ReactNode; k?: number }) {
  if (!items.length) return <p className="none">Nothing.</p>;
  return (
    <>
      {items.slice(0, k).map(render)}
      {items.length > k && (
        <details>
          <summary>{items.length - k} more</summary>
          <div>{items.slice(k).map((x, i) => render(x, i + k))}</div>
        </details>
      )}
    </>
  );
}

/** The node's final words for the turn, typed out once; shown whole if motion is reduced. */
function Typed({ text }: { text: string }) {
  const reduced = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [shown, setShown] = useState(reduced ? text.length : 0);
  const frame = useRef(0);
  useEffect(() => {
    if (reduced) return;
    const t0 = performance.now();
    const duration = Math.min(1600, text.length * 14);
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / duration);
      setShown(Math.round(k * text.length));
      if (k < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [text, reduced]);
  return (
    <div className="think q">
      {text.slice(0, shown)}
      {shown < text.length && <i className="caret" />}
    </div>
  );
}

// ---- beliefs and why -----------------------------------------------------------------------------

function tagFor(b: BeliefView, status: string): [string, string] {
  if (DROPPED.has(status)) return ["dropped", "var(--stale)"];
  if (status === "suspect") return ["suspect", "var(--fire)"];
  if (b.origin === "derived") return ["worked out", "var(--muted)"];
  if (b.origin === "observed") return ["seen", "var(--ok)"];
  return ["holds", "var(--accent)"];
}

function Beliefs({ space, node, tick, belief, why, onBelief, onOpen }: Props) {
  const all = (space.beliefs[node] ?? [])
    .map((b) => ({ b, status: statusAt(b, tick) }))
    .filter((x): x is { b: BeliefView; status: string } => x.status !== null)
    .sort((x, y) => Number(LIVE.has(y.status)) - Number(LIVE.has(x.status)) || y.b.born - x.b.born);
  const open = all.find((x) => x.b.id === belief);
  const ordered = open ? [open, ...all.filter((x) => x !== open)] : all;
  if (!(node in space.beliefs)) {
    return (
      <div className="sec">
        <div className="eyebrow">Believes</div>
        <p className="none">A code node keeps no beliefs of its own; it acts on everyone else's.</p>
      </div>
    );
  }
  const row = ({ b, status }: { b: BeliefView; status: string }) => {
    const [label, colour] = tagFor(b, status);
    const expanded = b.id === belief;
    return (
      <li key={b.id} className="bi">
        <button className={`brow ${DROPPED.has(status) ? "stale" : ""}`} aria-expanded={expanded} onClick={() => onBelief(expanded ? null : b.id)}>
          <span className="what">
            <span className="chev">▸</span> <b>{b.text}</b> <small>{b.id} · {originText(b)}</small>
          </span>
          <span className="tag" style={c(colour)}>{label}</span>
        </button>
        {expanded && <WhyChain why={why} node={node} tick={tick} onOpen={onOpen} />}
      </li>
    );
  };
  const live = all.filter((x) => LIVE.has(x.status)).length;
  return (
    <div className="sec">
      <div className="eyebrow">
        Believes · {live} live{all.length > live ? `, ${all.length - live} dropped` : ""} <span className="hint">· tap one to see why</span>
      </div>
      {all.length ? (
        <>
          <ul className="bl">{ordered.slice(0, 6).map(row)}</ul>
          {ordered.length > 6 && (
            <details>
              <summary>{ordered.length - 6} more</summary>
              <ul className="bl">{ordered.slice(6).map(row)}</ul>
            </details>
          )}
        </>
      ) : (
        <p className="none">No beliefs yet.</p>
      )}
    </div>
  );
}

function WhyChain({ why, node, tick, onOpen }: { why: Why | null; node: string; tick: number; onOpen: (node: string, belief: string | null) => void }) {
  if (!why) return <div className="why"><p className="none">Tracing…</p></div>;
  const chip = (who: string, id: string, text = id) => (
    <button key={`${who}${id}`} className="chip" onClick={() => onOpen(who, id)}>{text}</button>
  );
  const b = why.belief;
  const cut = new Set(why.cut_by_distrust);
  const changes = why.changes.filter((x) => x.tick <= tick);
  const status = changes.length ? changes[changes.length - 1]!.status : "active";
  const told = why.upstream.filter((u) => u.kind !== "evidence");
  const routes = told.map((u) => (u.route?.length ? u.route : u.sender ? [u.sender] : []));
  const alive = routes.filter((r) => !r.some((h) => cut.has(h))).length;
  return (
    <div className="why">
      {why.upstream.filter((u) => u.kind === "evidence").map((u) => (
        <div key={u.observation} className="step">
          <span className="k">SOURCE · {u.tick}</span>
          Seen directly{u.item ? ` (${u.item})` : ""}: a system of record or a check, so no one can make it stale.
        </div>
      ))}
      {told.map((u, k) => {
        const hops = [...routes[k]!, node];
        const isCut = hops.some((h) => cut.has(h));
        return (
          <div key={u.observation} className={`step ${isCut ? "cut" : ""}`}>
            <span className="k">SUPPORTS · route{u.item ? ` · ${u.item}` : ""}</span>
            {hops.map((h, i) => (
              <span key={i}>
                {i > 0 && " → "}
                <span className={cut.has(h) ? "r" : undefined}>{h}</span>
              </span>
            ))}
            {u.source_belief && u.sender && <> · their {chip(u.sender, u.source_belief)}</>}
          </div>
        );
      })}
      {why.derived_from.length > 0 && (
        <div className="step">
          <span className="k">DERIVED_FROM</span>
          {why.derived_from.map((d) => <div key={d.belief}>{chip(node, d.belief)} {d.text} <small>({d.status})</small></div>)}
        </div>
      )}
      {changes.map((x, k) => (
        <div key={`c${k}`} className="step cut">
          <span className="k">{x.status.toUpperCase()} · tick {x.tick}</span>
          <span className="reason">{x.reason}</span>
        </div>
      ))}
      <div className="step" style={c(DROPPED.has(status) ? "var(--stale)" : "var(--accent)")}>
        <span className="verdict" style={{ color: DROPPED.has(status) ? "var(--stale)" : undefined }}>
          {routes.length > 0 && alive < routes.length && `${alive} of ${routes.length} route${routes.length === 1 ? "" : "s"} left → `}
          {DROPPED.has(status) ? `dropped (${status})` : status === "suspect" ? "flagged: something it rests on changed" : "still holds"}
        </span>
      </div>
      <div className="step">
        <span className="k">RESTS ON IT</span>
        {why.dependents.length
          ? why.dependents.map((d) => (
              <div key={d.id}>
                {d.id.startsWith("X") ? <span className="chip static">{d.text}</span> : chip(node, d.id)} {d.id.startsWith("X") ? "" : d.text}{" "}
                <small>({d.status}, {d.hops} step{d.hops > 1 ? "s" : ""})</small>
              </div>
            ))
          : "Nothing yet."}
      </div>
      <div className="step" style={c(why.downstream.length ? "var(--gold)" : "var(--line)")}>
        <span className="k">PASSED ON</span>
        {why.downstream.length
          ? why.downstream.map((d) => <span key={`${d.node}${d.belief}`}>{chip(d.node, d.belief, `${d.node} · ${d.belief}`)} <small>{d.status}</small> </span>)
          : "Not passed on."}
      </div>
      {why.actions.length > 0 && (
        <div className="step" style={c("var(--gold)")}>
          <span className="k">ACTIONS RESTING ON IT</span>
          {why.actions.map((a) => <div key={a.id}>{a.id} {callText(a)} <small>{a.status}</small></div>)}
        </div>
      )}
      <details>
        <summary>Graph queries for this belief ({why.store === "FalkorStore" ? "run live on FalkorDB" : "as FalkorDB runs them"})</summary>
        {Object.entries(why.cypher).map(([name, query]) => (
          <div key={name}>
            <p>{name}{why.live[name] ? ` · ${why.live[name]!.ms} ms, ${why.live[name]!.rows.length} rows` : ""}</p>
            <pre>{query.replaceAll("$id", `'${b.id}'`)}</pre>
          </div>
        ))}
      </details>
    </div>
  );
}

function Actions({ space, node, tick }: { space: SpaceState; node: string; tick: number }) {
  const mine = space.proposals.filter((p) => p.node === node && p.tick <= tick);
  if (!mine.length) return null;
  const colour: Record<string, string> = {
    done: "var(--ok)", pending: "var(--accent)", held: "var(--gold)", reviewed: "var(--gold)",
    shadow: "var(--muted)", rejected: "var(--stale)", failed: "var(--stale)",
  };
  return (
    <div className="sec">
      <div className="eyebrow">Actions · {mine.length}</div>
      <ul className="bl">
        {mine.slice(-6).map((p) => (
          <li key={p.id} className={`act ${p.status}`}>
            <span>{callText(p)}<small>{p.status === "held" || p.status === "reviewed" ? p.note : p.result}</small></span>
            <span className="tag" style={c(colour[p.status] ?? "var(--muted)")}>{p.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
