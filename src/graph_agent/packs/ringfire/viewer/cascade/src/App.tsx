import { useCallback, useEffect, useMemo, useState } from "react";
import { Network } from "./components/Network";
import { Timeline } from "./components/Timeline";
import { World } from "./components/World";
import { A, findBelief, hasBeliefs, isImposter, lastDay, opening } from "./model";
import type { CascadeData } from "./types";

export interface Selection {
  agent: number | null;
  belief: string | null; // the belief whose chain is open in the agent's card
}

export function App({ data }: { data: CascadeData }) {
  const start = useMemo(() => opening(data), [data]);
  const labels = Object.keys(data.runs);
  const s = data.scenario;
  const [label, setLabel] = useState(start.run);
  const [day, setDayRaw] = useState(start.day);
  const [sel, setSel] = useState<Selection>({ agent: start.agent, belief: start.belief });
  const [reveal, setReveal] = useState(false);
  const [playing, setPlaying] = useState(false);
  const run = data.runs[label]!;
  const end = lastDay(run);
  const dense = s.n_agents > 24;

  const setDay = useCallback((d: number) => setDayRaw(Math.max(0, Math.min(end, d))), [end]);
  const openAgent = useCallback((agent: number | null, belief: string | null = null) => setSel({ agent, belief }), []);

  // switching runs keeps the agent open; its open belief only if the other run has it too
  const switchRun = (next: string) => {
    setLabel(next);
    setDayRaw((d) => Math.min(d, lastDay(data.runs[next]!)));
    if (sel.agent !== null && sel.belief && !findBelief(data.runs[next]!, sel.agent, sel.belief))
      setSel({ agent: sel.agent, belief: null });
  };

  useEffect(() => {
    if (!playing) return;
    if (day >= end) return setPlaying(false);
    const t = setTimeout(() => setDay(day + 1), dense ? 900 : 2600);
    return () => clearTimeout(t);
  }, [playing, day, end, dense, setDay]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") openAgent(null);
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "ArrowRight") (setPlaying(false), setDay(day + 1));
      if (e.key === "ArrowLeft") (setPlaying(false), setDay(day - 1));
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [day, setDay, openAgent]);

  const find = (value: string) => {
    const n = Number(value.trim().toUpperCase().replace(/^A/, ""));
    if (Number.isInteger(n) && n >= 0 && n < s.n_agents) openAgent(n);
  };

  const imposters = Object.keys(s.imposters).length;
  return (
    <div className="wrap">
      <header className="top">
        <div className="brand">
          <h1>Cascade</h1>
          <p>
            Ring Fire · {s.n_agents} agents, {imposters} of them imposter{imposters === 1 ? "" : "s"} · {run.model || "model n/a"} ·
            seed {s.seed}
          </p>
        </div>
        <div className="controls">
          {labels.length > 1 && (
            <div className="seg" role="group" aria-label="System">
              {labels.map((l) => (
                <button key={l} aria-pressed={l === label} onClick={() => switchRun(l)} title={data.runs[l]!.system}>
                  {l}
                </button>
              ))}
            </div>
          )}
          <input
            className="search"
            placeholder="A12"
            aria-label="Find agent"
            list="agents"
            onKeyDown={(e) => e.key === "Enter" && e.currentTarget.blur()}
            onBlur={(e) => (find(e.currentTarget.value), (e.currentTarget.value = ""))}
          />
          <datalist id="agents">
            {Array.from({ length: s.n_agents }, (_, i) => (
              <option key={i} value={A(i)} />
            ))}
          </datalist>
          <label className="check">
            <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} /> Reveal imposters
          </label>
        </div>
      </header>

      <Timeline
        scenario={s}
        run={run}
        day={day}
        playing={playing}
        onDay={(d) => (setPlaying(false), setDay(d))}
        onPlay={() => {
          if (playing) return setPlaying(false);
          if (day >= end) setDay(0);
          setPlaying(true);
        }}
        onNextCut={() => jump((d) => run.exposures.some((e) => e.day === d))}
        onNextLie={() => jump((d) => run.messages.some((m) => m.day === d && m.altered && !isImposter(s, m.sender)))}
      />

      <div className="main">
        <Network
          scenario={s}
          run={run}
          label={label}
          day={day}
          reveal={reveal}
          sel={sel}
          onSelect={openAgent}
          memoryNote={hasBeliefs(run) ? null : `${label} keeps no belief graph: its agents re-read their messages every turn.`}
        />
        <World scenario={s} run={run} day={day} open={sel.agent} onOpen={(a) => openAgent(a)} />
      </div>
    </div>
  );

  function jump(pred: (d: number) => boolean) {
    setPlaying(false);
    for (let d = day + 1; d <= end; d++) if (pred(d)) return setDay(d);
  }
}
