import { type CSSProperties, forwardRef, type ReactNode, useEffect, useRef, useState } from "react";
import { DOWNSTREAM, EXPOSE_RECOUNT, SUPPORT_ROUTES } from "../cypher";
import { A, beliefsAt, droppedOn, findBelief, isDropped, isImposter, originText, routeCuts, statusAt } from "../model";
import type { BeliefView, MessageView, RunView, ScenarioView } from "../types";
import { c } from "./css";

interface Props {
  style: CSSProperties;
  scenario: ScenarioView;
  run: RunView;
  label: string;
  agent: number;
  day: number;
  reveal: boolean;
  belief: string | null;
  onBelief: (id: string | null) => void;
  onOpen: (agent: number, belief: string | null) => void;
  onClose: () => void;
  memoryNote: string | null;
}

/** One agent on one day: what it was thinking, the day's messages as a chat, and its beliefs. */
export const AgentCard = forwardRef<HTMLDivElement, Props>(function AgentCard(p, ref) {
  const { scenario, run, agent, day, reveal } = p;
  const turn = run.turns[`${agent}|${day}`];
  const today = run.messages.filter((m) => m.day === day);
  const heard = today.filter((m) => m.receiver === agent);
  const said = today.filter((m) => m.sender === agent);
  const fpa = scenario.fields_per_agent;
  const distrusts = [...new Set(run.exposures.filter((e) => e.day <= day && e.viewer === agent).map((e) => e.distrusted))];

  return (
    <div className="card in" ref={ref} style={p.style} key={agent} onClick={(e) => e.stopPropagation()}>
      <div className="card-h">
        <span className="name">{A(agent)}</span>
        <span className="tag">owns F{agent * fpa}{fpa > 1 ? `–F${agent * fpa + fpa - 1}` : ""}</span>
        {reveal && isImposter(scenario, agent) && <span className="tag" style={c("var(--lie)")}>imposter</span>}
        <button className="x" onClick={p.onClose} aria-label="Close">✕</button>
      </div>

      <div className="sec">
        <div className="eyebrow">Thinking · day {day}</div>
        {turn ? (
          <Typed key={`${p.label}|${agent}|${day}`} text={turn.final || "(no reply)"} />
        ) : (
          <p className="none">{reveal && isImposter(scenario, agent) ? "An imposter: scripted, no model turn." : "Did not take a turn today."}</p>
        )}
        {turn && turn.steps.length > 0 && (
          <details>
            <summary>{turn.steps.length} tool call{turn.steps.length > 1 ? "s" : ""}</summary>
            <ul>
              {turn.steps.map((s, k) => (
                <li key={k} className={s.error ? "err" : ""}>
                  {s.tool}({Object.values(s.arguments).map(String).join(", ")}) → {s.result}
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>

      <div className="sec">
        <div className="eyebrow">Chat · {heard.length} in, {said.length} out</div>
        <div className="chat">
          <Capped k={5} items={[...heard.map((m) => [m, "in"] as const), ...said.map((m) => [m, "out"] as const)]}
            render={([m, dir], k) => <Bubble key={k} m={m} dir={dir} reveal={reveal} scenario={scenario} />} />
        </div>
      </div>

      {p.memoryNote === null ? (
        <Beliefs {...p} />
      ) : (
        <div className="sec">
          <div className="eyebrow">Believes</div>
          <p className="none">{p.memoryNote}</p>
        </div>
      )}

      {distrusts.length > 0 && (
        <div className="sec">
          <div className="eyebrow">Trust</div>
          <p className="none" style={{ color: "var(--stale)" }}>
            Stopped trusting {distrusts.map(A).join(", ")}: their claims didn't match the evidence.
          </p>
        </div>
      )}
    </div>
  );
});

function Bubble({ m, dir, reveal, scenario }: { m: MessageView; dir: "in" | "out"; reveal: boolean; scenario: ScenarioView }) {
  const other = dir === "out" ? m.receiver : m.sender;
  const lie = m.altered && reveal;
  return (
    <div className={`row ${dir} ${reveal && isImposter(scenario, other) ? "liar" : ""}`}>
      <span className="who" title={A(other)}>{A(other)}</span>
      <div className={`bub ${lie ? "false" : ""}`}>
        {dir === "out" && <><b>to {A(other)}</b> · </>}
        Fire reaches F{m.field} on day {m.claim_day}.
        {lie && <> <span className="tag" style={c("var(--lie)")}>false</span></>}
        <small>{m.route.length > 1 ? `relayed ${m.route.map(A).join(" → ")}` : "first-hand"}</small>
      </div>
    </div>
  );
}

function Capped<T>({ items, render, k = 3 }: { items: T[]; render: (item: T, key: number) => ReactNode; k?: number }) {
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

/** The agent's final text for the turn, typed out once; shown whole if motion is reduced. */
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

function Beliefs({ run, agent, day, belief, onBelief, onOpen }: Props) {
  const all = beliefsAt(run, agent, day);
  const open = all.find((b) => b.id === belief);
  const ordered = open ? [open, ...all.filter((b) => b !== open)] : all;
  const row = (b: BeliefView) => {
    const status = statusAt(run, b, day);
    const tag = isDropped(status)
      ? ["dropped", "var(--stale)"]
      : status === "suspect"
        ? ["suspect", "var(--fire)"]
        : b.origin === "derived"
          ? ["worked out", "var(--muted)"]
          : ["holds", "var(--accent)"];
    const expanded = b === open;
    return (
      <li key={b.id} className="bi">
        <button className={`brow ${isDropped(status) ? "stale" : ""}`} aria-expanded={expanded} onClick={() => onBelief(expanded ? null : b.id)}>
          <span className="what">
            <span className="chev">▸</span> <b>F{b.field} burns day {String(b.value)}</b> <small>{originText(b)}</small>
          </span>
          <span className="tag" style={c(tag[1]!)}>{tag[0]}</span>
        </button>
        {expanded && <WhyChain run={run} agent={agent} day={day} b={b} onOpen={onOpen} />}
      </li>
    );
  };
  return (
    <div className="sec">
      <div className="eyebrow">
        Believes · {all.length} <span className="hint">· tap one to see why</span>
      </div>
      {all.length ? (
        <>
          <ul className="bl">{ordered.slice(0, 5).map(row)}</ul>
          {ordered.length > 5 && (
            <details>
              <summary>{ordered.length - 5} more</summary>
              <ul className="bl">{ordered.slice(5).map(row)}</ul>
            </details>
          )}
        </>
      ) : (
        <p className="none">No beliefs yet.</p>
      )}
    </div>
  );
}

function WhyChain({ run, agent, day, b, onOpen }: { run: RunView; agent: number; day: number; b: BeliefView; onOpen: (agent: number, belief: string | null) => void }) {
  const dropped = droppedOn(run, b, day);
  const chip = (who: number, id: string, text = id) => (
    <button key={`${who}${id}`} className="chip" onClick={() => onOpen(who, id)}>{text}</button>
  );
  const own = (id: string) => findBelief(run, agent, id);
  const describe = (x: BeliefView | undefined) => (x ? ` F${x.field} burns day ${String(x.value)}, ${originText(x)}` : "");

  const alive = b.routes.filter((rt) => routeCuts(b, rt, day).length === 0).length;
  const dependents = b.dependents.filter((id) => (own(id)?.born ?? 0) <= day);
  const sent = b.sent.filter((s) => s.day <= day);
  const sentDays = [...new Set(sent.map((s) => s.day))];
  const became = b.became.filter((x) => (findBelief(run, x.agent, x.id)?.born ?? Infinity) <= day);
  const query = b.origin === "told" ? (b.cuts.some((x) => x.day <= day) ? EXPOSE_RECOUNT : SUPPORT_ROUTES) : DOWNSTREAM;

  return (
    <div className="why">
      {b.origin === "observed" && (
        <div className="step"><span className="k">SOURCE</span>Seen directly. A sensor observation, no relay, so no other agent can make it stale.</div>
      )}
      {b.origin === "derived" && (
        <div className="step">
          <span className="k">DERIVED_FROM</span>
          {b.sources.length
            ? b.sources.map((id) => <div key={id}>{chip(agent, id)}{describe(own(id))}</div>)
            : "Worked out by the agent, with no recorded parent."}
        </div>
      )}
      {b.origin === "told" && (
        <>
          {b.routes.map((rt, k) => {
            const cutBy = new Set(routeCuts(b, rt, day).map((x) => x.agent));
            return (
              <div key={k} className={`step ${cutBy.size ? "cut" : ""}`}>
                <span className="k">SUPPORTS · route</span>
                {[...rt, agent].map((h, i) => (
                  <span key={i}>
                    {i > 0 && " → "}
                    <span className={cutBy.has(h) ? "r" : undefined}>{A(h)}</span>
                  </span>
                ))}
              </div>
            );
          })}
          {b.cuts.filter((x) => x.day <= day).map((x, k) => (
            <div key={`c${k}`} className="step cut">
              <span className="k">TRUST CUT · day {x.day}</span>
              <span className="reason">Stopped trusting {A(x.agent)}{x.reason ? `: ${x.reason}` : ""}.</span>
            </div>
          ))}
          <div className="step" style={c(dropped !== null ? "var(--stale)" : "var(--accent)")}>
            <span className="verdict" style={{ color: dropped !== null ? "var(--stale)" : undefined }}>
              {alive} of {b.routes.length} route{b.routes.length === 1 ? "" : "s"} left{dropped !== null ? ` → dropped on day ${dropped}` : " → still holds"}
            </span>
          </div>
        </>
      )}
      <div className="step">
        <span className="k">RESTS ON IT</span>
        {dependents.length ? (
          <>
            {dependents.map((id) => <div key={id}>{chip(agent, id)}{describe(own(id))}</div>)}
            {dropped !== null && <span className="reason">Marked suspect: they were derived from a dropped belief.</span>}
          </>
        ) : dropped !== null ? "Nothing. The cut touched only this belief." : "Nothing yet."}
      </div>
      <div className="step" style={c(sent.length ? "var(--gold)" : "var(--line)")}>
        <span className="k">PASSED ON</span>
        {sent.length ? (
          <>
            {sentDays.map((d) => `day ${d} → ${sent.filter((s) => s.day === d).map((s) => A(s.to)).join(", ")}`).join("; ")}
            {became.length > 0 && <div>{became.map((x) => <span key={x.id}>{chip(x.agent, x.id)} in {A(x.agent)}'s memory </span>)}</div>}
          </>
        ) : dropped !== null ? (
          <><b>Never.</b> Dropped on day {dropped} without being passed on.</>
        ) : (
          "Not passed on."
        )}
      </div>
      <details>
        <summary>Graph query for this step</summary>
        <pre>{query}</pre>
        <p>
          {run.system === "graph-falkor"
            ? "This run used FalkorDB; this is the query it ran (src/graph_agent/stores/falkor.py)."
            : `The FalkorDB store's query (src/graph_agent/stores/falkor.py). This run (${run.system}) used another store that applies the same rule.`}
        </p>
      </details>
    </div>
  );
}
