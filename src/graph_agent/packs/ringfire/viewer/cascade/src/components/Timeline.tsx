import { caption, dayStats, lastDay } from "../model";
import type { RunView, ScenarioView } from "../types";
import { c } from "./css";

interface Props {
  scenario: ScenarioView;
  run: RunView;
  day: number;
  playing: boolean;
  onDay: (day: number) => void;
  onPlay: () => void;
  onNextCut: () => void;
  onNextLie: () => void;
}

const W = 1000;
const H = 54;

/** Day controls, a one-line summary of the day, and a strip of every day's activity. */
export function Timeline({ scenario, run, day, playing, onDay, onPlay, onNextCut, onNextLie }: Props) {
  const end = lastDay(run);
  const stats = run.days.map((_, d) => dayStats(run, d));
  const max = Math.max(1, ...stats.map((x) => Math.max(x.fire, x.lies + x.truth)));
  const bw = W / Math.max(1, run.days.length);
  const y = (v: number) => (v / max) * (H - 10);

  return (
    <section className="tl" aria-label="Timeline">
      <div className="tl-row">
        <button className="btn" onClick={() => onDay(day - 1)} disabled={day === 0} aria-label="Previous day">
          ◂
        </button>
        <button className="btn" onClick={onPlay} aria-label={playing ? "Pause" : "Play"}>
          {playing ? "❚❚" : "▶"}
        </button>
        <button className="btn" onClick={() => onDay(day + 1)} disabled={day >= end} aria-label="Next day">
          ▸
        </button>
        <span className="daylabel">Day {day}</span>
        <button className="btn" onClick={onNextCut}>
          Next trust cut ▸
        </button>
        <button className="btn" onClick={onNextLie}>
          Next relayed lie ▸
        </button>
        <span className="caption">{caption(scenario, run, day)}</span>
      </div>
      <svg
        id="strip"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Activity per day; click to jump"
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          onDay(Math.floor(((e.clientX - box.left) / box.width) * run.days.length));
        }}
      >
        {stats.map((x, d) => {
          const x0 = d * bw + bw * 0.12;
          const w = bw * 0.76;
          return (
            <g key={d}>
              {d === day && <rect x={d * bw} y={0} width={bw} height={H} fill="var(--soft)" />}
              <rect x={x0} y={H - y(x.fire)} width={w * 0.45} height={y(x.fire)} fill="var(--fire)" opacity={0.85} />
              <rect x={x0 + w * 0.5} y={H - y(x.truth)} width={w * 0.5} height={y(x.truth)} fill="var(--accent)" opacity={0.55} />
              <rect x={x0 + w * 0.5} y={H - y(x.truth) - y(x.lies)} width={w * 0.5} height={y(x.lies)} fill="var(--lie)" />
              {x.cuts > 0 && <circle cx={d * bw + bw / 2} cy={5} r={Math.min(4.5, 2 + x.cuts / 3)} fill="var(--stale)" />}
            </g>
          );
        })}
        <rect x={day * bw} y={0} width={bw} height={H} fill="none" stroke="var(--ink)" strokeWidth={2} />
      </svg>
      <div className="strip-key">
        <span><i style={c("var(--fire)")} />fields on fire</span>
        <span><i style={c("var(--lie)")} />lies sent</span>
        <span><i style={c("var(--stale)")} />trust cuts</span>
        <span><i style={c("var(--accent)")} />true reports</span>
      </div>
    </section>
  );
}
