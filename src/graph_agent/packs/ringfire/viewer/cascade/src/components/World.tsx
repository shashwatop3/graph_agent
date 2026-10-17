import { useState } from "react";
import { A, type FieldState, owner, worldAt } from "../model";
import type { RunView, ScenarioView } from "../types";
import { c } from "./css";

interface Props {
  scenario: ScenarioView;
  run: RunView;
  day: number;
  open: number | null;
  onOpen: (agent: number) => void;
}

const LABEL: Record<FieldState, string> = { alive: "alive", burning: "on fire", burnt: "burnt", saved: "saved" };

/** The ground truth, which no agent sees: every field, its owner, and its state at the end of the day.
 * With many agents it switches to one block per owner. */
export function World({ scenario, run, day, open, onOpen }: Props) {
  const [onlyTouched, setOnlyTouched] = useState(false);
  const { n_agents: n, fields_per_agent: fpa, n_fields: F } = scenario;
  const dense = n > 24;
  const state = worldAt(run, day);
  const watered = new Set(run.days[day]?.watered ?? []);
  const at = (f: number): FieldState => state.get(f) ?? "alive";
  const count = (s: FieldState) => Array.from({ length: F }, (_, f) => at(f)).filter((x) => x === s).length;

  const stats: [string, string, number][] = [
    ["alive", "var(--alive)", count("alive") + count("saved")],
    ["on fire", "var(--fire)", count("burning")],
    ["burnt", "var(--burnt)", count("burnt")],
    ["saved by water", "var(--water)", count("saved")],
  ];

  return (
    <section className="panel">
      <div className="ph">
        <div>
          <div className="eyebrow">Ground truth · agents never see this</div>
          <h2>Real world</h2>
        </div>
        <span className="eyebrow">end of day {day}</span>
      </div>
      <div className="pb">
        <div className="stats">
          {stats.map(([label, colour, value]) => (
            <div className="stat" key={label}>
              <div className="n">{value}</div>
              <div className="l"><i style={c(colour)} />{label}</div>
            </div>
          ))}
        </div>
        <div className="wtools">
          <span className="eyebrow">{F} fields{dense ? " · one block per agent" : ""}</span>
          {dense && (
            <label className="check">
              <input type="checkbox" checked={onlyTouched} onChange={(e) => setOnlyTouched(e.target.checked)} /> Only fields touched by fire
            </label>
          )}
        </div>

        {!dense ? (
          <div className="fields">
            {Array.from({ length: F }, (_, f) => {
              const s = at(f);
              const o = owner(scenario, f);
              return (
                <div key={f} className={`f ${s} ${watered.has(o) ? "watered" : ""} ${open === o ? "sel" : ""}`} title={`F${f}, owned by ${A(o)}: ${LABEL[s]}`}>
                  <b>F{f}</b>
                  <span className="own">{A(o)} · {LABEL[s]}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="blocks">
            {Array.from({ length: n }, (_, o) => {
              const cells = Array.from({ length: fpa }, (_, k) => o * fpa + k);
              const hot = cells.some((f) => state.has(f));
              if (onlyTouched && !hot && open !== o) return null;
              return (
                <button key={o} className={`blk ${hot ? "hot" : ""} ${open === o ? "sel" : ""}`} onClick={() => onOpen(o)}
                  title={`${A(o)}: ${cells.map((f) => `F${f} ${LABEL[at(f)]}`).join(", ")}${watered.has(o) ? " · watered today" : ""}`}>
                  <span className="cells">
                    {cells.map((f) => (
                      <span key={f} className={`c ${state.get(f) ?? ""} ${watered.has(o) && !state.has(f) ? "watered" : ""}`} />
                    ))}
                  </span>
                  <span className="t">{A(o)}</span>
                </button>
              );
            })}
          </div>
        )}
        <p className="note">
          {dense
            ? `Each block is one agent's ${fpa} field${fpa > 1 ? "s" : ""}. Blue cells were saved by water; a blue outline means the owner watered today. Click a block to open that agent.`
            : "Each tag names the agent that owns the field. Fire spreads along the ring. A field watered on the day fire arrives is saved."}
        </p>
      </div>
    </section>
  );
}
