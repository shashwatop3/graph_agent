import { useEffect, useState } from "react";
import { c } from "../css";
import { SetupCards } from "../setups/SetupsView";
import "./landing.css";

const REPO = "https://github.com/shashwatop3/graph_agent";

/** The front page: what Groundwork does, how its agents use the FalkorDB graph, and why that
 * beats a chat log or shared notes, drawn rather than told. Then the three setups to try. */
export function Landing({ onSetups, onOpen }: { onSetups: () => void; onOpen: (id: string) => void }) {
  return (
    <div className="landing">
      <section className="l-hero">
        <div className="l-hero-text">
          <div className="eyebrow">Groundwork · agents on FalkorDB</div>
          <h2>Agents that remember <em>why</em> they believe things</h2>
          <p>
            A team of AI agents shares one memory: a belief graph in FalkorDB. Every belief records what it came
            from, and every plan records the beliefs it rests on. So when a fact changes or a teammate turns out to
            have lied, the correction follows the graph to exactly what it touched, and nothing else.
          </p>
          <div className="l-cta">
            <button className="btn primary big" onClick={() => onOpen("fire")}>Try the fire sim, free</button>
            <button className="btn big" onClick={onSetups}>See the three setups</button>
            <a className="linkish" href={REPO} target="_blank" rel="noreferrer">Source on GitHub</a>
          </div>
        </div>
        <CorrectionStory />
      </section>

      <section className="l-section">
        <Head eyebrow="How it works" title="Agents never share a transcript. They share a graph." />
        <ToolsDiagram />
        <div className="l-steps">
          <Step n={1} colour="var(--water)" title="Observe" node="Observation">
            Everything an agent receives (a feed item, a sensor reading, a teammate's message) becomes an
            Observation, with a <code>RELAYED_VIA</code> edge for every agent it passed through.
          </Step>
          <Step n={2} colour="var(--accent)" title="Believe" node="Belief">
            The agent asserts a Belief that the observation <code>SUPPORTS</code>: a subject, a predicate and a value,
            with an origin (observed, told or derived) and a status.
          </Step>
          <Step n={3} colour="var(--gold)" title="Build on it" node="Action">
            Plans and actions point back at what they rely on with <code>DERIVED_FROM</code>, at any depth: the trip
            rests on the date, the budget on the trips.
          </Step>
          <Step n={4} colour="var(--stale)" title="Correct" node="Correction">
            A Correction marks what it <code>INVALIDATED</code>. The store walks <code>DERIVED_FROM</code> backwards
            and turns everything built on it suspect, to be redone.
          </Step>
        </div>
      </section>

      <section className="l-section">
        <Head eyebrow="How agents interact" title="A lie can be traced to where it started" />
        <div className="l-split">
          <RelayDiagram />
          <div className="l-prose">
            <p>
              Agents talk with <code>send</code>. The receiver does not get a bare string: it gets a new Observation whose
              route is one hop longer. So every claim carries the full path it travelled.
            </p>
            <p>
              A checker (code, not a model) tests what agents were told against the evidence. When a claim is refuted, it
              blames the <b>first hop</b> on the route: the agent who made it up. The honest teammates who passed it on
              keep their trust.
            </p>
            <p>
              The liar is exposed, and the graph recounts each belief's routes. A belief whose only routes ran through the
              liar turns <b className="t-stale">stale</b>; one the venue or a sensor also confirmed stays active.
            </p>
          </div>
        </div>
      </section>

      <section className="l-section">
        <Head eyebrow="Why a graph" title="What a chat log or shared notes cannot tell an agent" />
        <Comparison />
      </section>

      <section className="l-section">
        <Head eyebrow="Inside FalkorDB" title="The queries doing the work" />
        <div className="l-queries">
          <Query title="Where a belief came from" body="Every supporting observation, with the route it took, for the Why panel and for blame.">
{`MATCH (o:Observation)-[:SUPPORTS]->(b:Belief {id: $id})
OPTIONAL MATCH (o)-[r:RELAYED_VIA]->(a:Agent)
RETURN o.id, collect([r.hop, a.id])`}
          </Query>
          <Query title="What rests on it" body="Breadth-first, one level per query, so a deep plan never blows up into every path.">
{`MATCH (s:Node)<-[:DERIVED_FROM]-(d)
WHERE s.id IN $frontier AND d.owner = $viewer
RETURN DISTINCT d.id, labels(d), d.status`}
          </Query>
          <Query title="A liar exposed" body="Count each belief's routes that avoid every exposed agent. None left: stale.">
{`MATCH (o:Observation)-[:SUPPORTS]->(b:Belief {owner: $viewer})
OPTIONAL MATCH (o)-[:RELAYED_VIA]->(a:Agent)
WITH b, o, collect(a.id) AS route
WITH b, sum(CASE WHEN size([x IN route
  WHERE x IN $exposed]) = 0 THEN 1 ELSE 0 END) AS alive
SET b.support_routes = alive`}
          </Query>
        </div>
        <p className="note">Each run gets its own graph (<code>space_&lt;id&gt;</code>), dropped when the run closes. Every query is in <code>stores/falkor.py</code>.</p>
      </section>

      <section className="l-section">
        <Head eyebrow="Try it" title="Three ready-made teams, three things the graph does" />
        <SetupCards onOpen={onOpen} />
        <div className="l-cta center">
          <button className="btn primary big" onClick={onSetups}>How to run them, step by step →</button>
        </div>
      </section>
    </div>
  );
}

function Head({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="l-head">
      <div className="eyebrow">{eyebrow}</div>
      <h2>{title}</h2>
    </div>
  );
}

function Step({ n, colour, title, node, children }: { n: number; colour: string; title: string; node: string; children: React.ReactNode }) {
  return (
    <div className="l-step" style={c(colour)}>
      <div className="l-step-top"><span className="l-num">{n}</span><h3>{title}</h3><span className="tag">{node}</span></div>
      <p>{children}</p>
    </div>
  );
}

function Query({ title, body, children }: { title: string; body: string; children: string }) {
  return (
    <div className="l-query">
      <h3>{title}</h3>
      <p>{body}</p>
      <pre><code>{children}</code></pre>
    </div>
  );
}

// ---- the hero: one correction, exactly its reach ----------------------------------------------

const STORY = [
  { caption: "The venue writes: the offsite is on Friday. The agent records an observation and the belief it supports." },
  { caption: "The desks build on it. Each trip, the rooms and the booking point back at the date with DERIVED_FROM. The agenda rests on something else." },
  { caption: "Wednesday: the venue moves it to Saturday. A correction invalidates the Friday belief." },
  { caption: "The graph walks back from Friday: exactly the plans built on it turn suspect. The agenda is left alone." },
  { caption: "The desks redo only those: new trips and a new booking, resting on Saturday." },
];

type N = { id: string; x: number; y: number; label: string; kind: "obs" | "belief" | "action" | "corr" };
const NODES: N[] = [
  { id: "o1", x: 70, y: 80, label: "venue mail", kind: "obs" },
  { id: "fri", x: 270, y: 80, label: "date = Fri", kind: "belief" },
  { id: "trip", x: 495, y: 28, label: "Eli's trip: Thu", kind: "belief" },
  { id: "rooms", x: 495, y: 152, label: "rooms: Thu night", kind: "belief" },
  { id: "book", x: 665, y: 90, label: "book train", kind: "action" },
  { id: "o2", x: 70, y: 250, label: "agenda doc", kind: "obs" },
  { id: "agenda", x: 270, y: 250, label: "Ana runs session 2", kind: "belief" },
  { id: "corr", x: 270, y: 168, label: "now Saturday", kind: "corr" },
];
const HALF = { obs: [52, 16], belief: [74, 16], action: [52, 16], corr: [64, 19] } as const;
/** Where the line from a's centre towards b leaves a's shape (a box, near enough). */
function rim(a: N, b: N): [number, number] {
  const [w, h] = HALF[a.kind];
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = Math.min(dx ? w / Math.abs(dx) : Infinity, dy ? h / Math.abs(dy) : Infinity);
  return [a.x + dx * t, a.y + dy * t];
}
const at = Object.fromEntries(NODES.map((n) => [n.id, n]));
const EDGES: [string, string, string, number][] = [ // from, to, label, first step shown
  ["o1", "fri", "SUPPORTS", 0],
  ["trip", "fri", "DERIVED_FROM", 1],
  ["rooms", "fri", "DERIVED_FROM", 1],
  ["book", "trip", "DERIVED_FROM", 1],
  ["o2", "agenda", "SUPPORTS", 1],
  ["corr", "fri", "INVALIDATED", 2],
];

function statusOf(id: string, step: number): string {
  if (id === "fri") return step >= 2 ? "stale" : "active";
  if (["trip", "rooms", "book"].includes(id)) return step === 3 ? "suspect" : step === 4 ? "redone" : "active";
  return "active";
}
const shownAt = (id: string) => (id === "o1" || id === "fri" ? 0 : id === "corr" ? 2 : 1);

function CorrectionStory() {
  const [step, setStep] = useState(0);
  const [playing, setPlaying] = useState(() => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => setStep((s) => (s + 1) % STORY.length), step === STORY.length - 1 ? 4200 : 3000);
    return () => window.clearTimeout(t);
  }, [step, playing]);
  return (
    <figure className="l-story panel">
      <svg viewBox="0 0 725 280" role="img" aria-label="A belief graph: a correction reaches only the plans built on the changed belief">
        <defs>
          <marker id="l-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0,0 L10,5 L0,10 z" fill="var(--muted)" />
          </marker>
        </defs>
        {EDGES.map(([f, t, label, from]) => {
          const a = at[f]!, b = at[t]!;
          const hot = label === "INVALIDATED" || (step === 3 && label === "DERIVED_FROM" && f !== "o2");
          const [x1, y1] = rim(a, b), [x2, y2] = rim(b, a);
          const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
          return (
            <g key={f + t} className={`l-edge ${step >= from ? "on" : ""} ${hot ? "hot" : ""}`}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} markerEnd="url(#l-arrow)" />
              <text x={mx + (x1 === x2 ? 8 : 0)} y={my - (x1 === x2 ? -3 : 6)} textAnchor={x1 === x2 ? "start" : "middle"}>{label}</text>
            </g>
          );
        })}
        {NODES.map((n) => {
          const status = statusOf(n.id, step);
          const label = n.id === "fri" && step === 4 ? "date = Sat" : n.id === "trip" && step === 4 ? "Eli's trip: Fri" : n.id === "rooms" && step === 4 ? "rooms: Fri night" : n.label;
          return (
            <g key={n.id} className={`l-node ${n.kind} ${status} ${step >= shownAt(n.id) ? "on" : ""}`} transform={`translate(${n.x},${n.y})`}>
              {n.kind === "corr"
                ? <path d={`M0,-${HALF.corr[1]} L${HALF.corr[0]},0 L0,${HALF.corr[1]} L-${HALF.corr[0]},0 Z`} />
                : <rect x={-HALF[n.kind][0]} y={-HALF[n.kind][1]} width={2 * HALF[n.kind][0]} height={2 * HALF[n.kind][1]} rx={n.kind === "obs" ? 16 : n.kind === "action" ? 4 : 8} />}
              <text y={4} textAnchor="middle">{label}</text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        <p aria-live="polite">{STORY[step]!.caption}</p>
        <div className="l-dots">
          <button className="btn" onClick={() => setPlaying((p) => !p)} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶"}</button>
          {STORY.map((_, i) => (
            <button key={i} className={`l-dot ${i === step ? "on" : ""}`} aria-label={`Step ${i + 1}`} aria-pressed={i === step} onClick={() => { setStep(i); setPlaying(false); }} />
          ))}
        </div>
        <div className="l-legend">
          <span style={c("var(--ok)")}><i />active</span>
          <span style={c("var(--gold)")}><i />suspect</span>
          <span style={c("var(--stale)")}><i />stale</span>
        </div>
      </figcaption>
    </figure>
  );
}

// ---- agents, their tools, the graph -----------------------------------------------------------

function ToolsDiagram() {
  const agents = ["Venue desk", "Travel desk", "Actions desk"];
  const reads = ["recall", "explain", "traverse", "shortest_path"];
  const writes = ["assert_belief", "retract", "send", "act"];
  return (
    <svg className="l-tools" viewBox="0 0 900 250" role="img" aria-label="Agents read and write a FalkorDB graph only through eight tools">
      {agents.map((a, i) => (
        <g key={a} transform={`translate(90,${55 + i * 70})`}>
          <circle r={24} fill="var(--panel)" stroke="var(--accent)" strokeWidth={1.6} />
          <text y={4} textAnchor="middle" fontSize={11} fill="var(--accent)">{`A${i}`}</text>
          <text y={42} textAnchor="middle" fontSize={11} fill="var(--muted)">{a}</text>
        </g>
      ))}
      <g transform="translate(330,20)">
        <rect width={220} height={210} rx={14} fill="var(--soft)" stroke="var(--line)" />
        <text x={110} y={24} textAnchor="middle" fontSize={10.5} fill="var(--muted)">TOOLS · core/tools.py</text>
        {reads.map((t, i) => <Pill key={t} x={10} y={40 + i * 40} label={t} colour="var(--water)" />)}
        {writes.map((t, i) => <Pill key={t} x={112} y={40 + i * 40} label={t} colour="var(--gold)" />)}
      </g>
      {[55, 125, 195].map((y) => <path key={y} className="l-flow" d={`M118,${y} C220,${y} 230,125 330,125`} />)}
      <path className="l-flow" d="M550,125 C600,125 610,125 660,125" />
      <g transform="translate(660,25)">
        <rect width={220} height={200} rx={14} fill="color-mix(in srgb, var(--fire) 7%, var(--panel))" stroke="var(--fire)" strokeWidth={1.4} />
        <text x={110} y={24} textAnchor="middle" fontSize={11} fill="var(--fire)" fontWeight={700}>FalkorDB · space_&lt;run&gt;</text>
        {[[50, 70], [110, 60], [170, 85], [70, 130], [140, 140], [110, 175], [185, 160]].map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={9} fill="var(--panel)" stroke={["var(--water)", "var(--accent)", "var(--accent)", "var(--gold)", "var(--accent)", "var(--stale)", "var(--gold)"][i]} strokeWidth={1.8} />
        ))}
        {[[50, 70, 110, 60], [110, 60, 170, 85], [110, 60, 70, 130], [70, 130, 140, 140], [170, 85, 140, 140], [110, 175, 140, 140], [185, 160, 140, 140]].map(([a, b, x, y], i) => (
          <line key={i} x1={a} y1={b} x2={x} y2={y} stroke="var(--line)" strokeWidth={1.3} />
        ))}
      </g>
      <text x={435} y={248} textAnchor="middle" fontSize={10.5} fill="var(--muted)">read on the left · write on the right · nothing else touches memory</text>
    </svg>
  );
}

function Pill({ x, y, label, colour }: { x: number; y: number; label: string; colour: string }) {
  return (
    <g transform={`translate(${x},${y})`}>
      <rect width={98} height={28} rx={14} fill="var(--panel)" stroke={colour} strokeWidth={1.3} />
      <text x={49} y={18} textAnchor="middle" fontSize={10} fill="var(--ink)">{label}</text>
    </g>
  );
}

// ---- a lie relayed, then traced back ------------------------------------------------------------

function RelayDiagram() {
  const hops = [
    { id: "A2", x: 70, role: "makes it up", liar: true },
    { id: "A1", x: 220, role: "relays it", liar: false },
    { id: "A0", x: 370, role: "relays it", liar: false },
  ];
  return (
    <svg className="l-relay panel" viewBox="0 0 520 250" role="img" aria-label="A false claim relayed through two honest agents; the checker blames the first hop">
      <defs>
        <marker id="l-arrow-r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" fill="var(--muted)" />
        </marker>
      </defs>
      <text x={20} y={30} fontSize={11} fill="var(--muted)">&quot;fire reaches field 7 on day 4&quot;</text>
      {hops.slice(0, -1).map((h, i) => (
        <g key={h.id} className="l-hop">
          <line x1={h.x + 26} y1={90} x2={hops[i + 1]!.x - 26} y2={90} stroke="var(--lie)" strokeWidth={1.8} markerEnd="url(#l-arrow-r)" />
          <text x={(h.x + hops[i + 1]!.x) / 2} y={80} textAnchor="middle" fontSize={10} fill="var(--muted)">send · hop {i + 1}</text>
        </g>
      ))}
      <line x1={396} y1={90} x2={470} y2={90} stroke="var(--line)" strokeWidth={1.4} strokeDasharray="4 4" />
      <text x={470} y={80} textAnchor="end" fontSize={10} fill="var(--muted)">…</text>
      {hops.map((h) => (
        <g key={h.id} transform={`translate(${h.x},90)`}>
          <circle r={24} fill="var(--panel)" stroke={h.liar ? "var(--lie)" : "var(--ok)"} strokeWidth={h.liar ? 2.6 : 1.8} />
          <text y={4} textAnchor="middle" fontSize={12} fill={h.liar ? "var(--lie)" : "var(--ink)"}>{h.id}</text>
          <text y={42} textAnchor="middle" fontSize={10.5} fill="var(--muted)">{h.role}</text>
        </g>
      ))}
      <path d="M370,150 C370,200 70,200 70,140" fill="none" stroke="var(--stale)" strokeWidth={1.6} strokeDasharray="5 4" markerEnd="url(#l-arrow-r)" />
      <text x={220} y={210} textAnchor="middle" fontSize={11} fill="var(--stale)">day 4, no fire: refuted, blame follows RELAYED_VIA to hop 1</text>
      <g transform="translate(70,236)"><text textAnchor="middle" fontSize={11} fill="var(--lie)" fontWeight={700}>exposed</text></g>
      <g transform="translate(295,236)"><text textAnchor="middle" fontSize={11} fill="var(--ok)">A1, A0 keep their trust</text></g>
    </svg>
  );
}

// ---- the comparison ---------------------------------------------------------------------------

const ROWS: [string, string, string][] = [
  ["A fact changes", "Every agent rereads the log and guesses what the change affected. Plans built on the old fact quietly survive.", "DERIVED_FROM leads to exactly the beliefs and actions built on it. They turn suspect and are redone; the rest is untouched."],
  ["An honest teammate passes on a lie", "Whoever said it last looks guilty, or nobody does.", "RELAYED_VIA keeps the whole route. The first hop is blamed; the relays keep their trust."],
  ["Why do you believe that?", "Search the transcript and hope.", "explain returns the supporting observations and every hop they took, in one query."],
  ["The liar turns out to be right after all", "No way back: what was thrown away is gone.", "A stale belief revives once one of its routes avoids everyone still exposed."],
  ["The team grows", "Every message lands in every context, so prompts grow with the team.", "Each agent recalls only the slice it needs, by entity, owner and status."],
];

function Comparison() {
  return (
    <div className="l-compare panel">
      <div className="l-row head"><span /><span>Chat log or shared notes</span><span>Groundwork's belief graph</span></div>
      {ROWS.map(([q, notes, graph]) => (
        <div className="l-row" key={q}>
          <b>{q}</b>
          <span className="worse">{notes}</span>
          <span className="better">{graph}</span>
        </div>
      ))}
      <p className="note pad-x">
        The offsite setup runs both ways: switch Memory to <i>Shared notes</i> to run the same desks on one notes file
        (it needs a real model), and compare the end-of-week checks. Ring Fire also runs on a relational store (PostgreSQL) for the same comparison.
      </p>
    </div>
  );
}
