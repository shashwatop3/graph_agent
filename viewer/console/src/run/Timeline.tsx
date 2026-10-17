import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";
import { caption, tickStats } from "./model";

interface Props {
  space: SpaceState;
  events: RunEvent[];
  tick: number;
  last: number; // the last tick played
  playing: boolean; // replaying the ticks already played
  onTick: (tick: number) => void;
  onPlay: () => void;
  onStep: () => void; // play one more tick on the server
  onRun: () => void; // play to the end on the server
  onPause: () => void;
  onNextCorrection: () => void;
  onNextHeld: () => void;
}

const W = 1000;
const H = 54;

/** Tick controls, a one-line summary of the tick, and a strip of every tick's activity: the Fire
 * game's timeline, for any team. */
export function Timeline(p: Props) {
  const { space, events, tick, last } = p;
  const ticks = Math.max(last + 1, space.team.settings?.ticks ?? last + 1);
  const stats = Array.from({ length: ticks }, (_, t) => tickStats(events, t));
  const max = Math.max(1, ...stats.map((s) => Math.max(s.items + s.turns, s.told + s.bad)));
  const bw = W / Math.max(1, ticks);
  const y = (v: number) => (v / max) * (H - 12);
  const label = space.clocks[tick] ?? `tick ${tick}`;

  return (
    <section className="tl" aria-label="Timeline">
      <div className="tl-row">
        <button className="btn" onClick={() => p.onTick(tick - 1)} disabled={tick === 0} aria-label="Previous tick">◂</button>
        <button className="btn" onClick={p.onPlay} aria-label={p.playing ? "Pause replay" : "Replay"} disabled={last === 0}>
          {p.playing ? "❚❚" : "▶"}
        </button>
        <button className="btn" onClick={() => p.onTick(tick + 1)} disabled={tick >= last} aria-label="Next tick">▸</button>
        <span className="daylabel">{label}</span>
        <span className="sep" />
        <button className="btn" onClick={p.onStep} disabled={space.running || space.finished} title="Play one more tick">Step ⏵</button>
        {space.running ? (
          <button className="btn" onClick={p.onPause}>Pause run</button>
        ) : (
          <button className="btn primary" onClick={p.onRun} disabled={space.finished} title="Play to the end">Run ⏵⏵</button>
        )}
        <button className="btn" onClick={p.onNextCorrection}>Next correction ▸</button>
        <button className="btn" onClick={p.onNextHeld}>Next held action ▸</button>
        <span className="caption">{caption(events, tick)}</span>
      </div>
      <svg
        id="strip"
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        role="img"
        aria-label="Activity per tick; click to jump"
        onClick={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          p.onTick(Math.min(last, Math.floor(((e.clientX - box.left) / box.width) * ticks)));
        }}
      >
        {stats.map((s, t) => {
          const x0 = t * bw + bw * 0.12;
          const w = bw * 0.76;
          const played = t <= last;
          return (
            <g key={t} opacity={played ? 1 : 0.25}>
              {t === tick && <rect x={t * bw} y={0} width={bw} height={H} fill="var(--soft)" />}
              <rect x={x0} y={H - y(s.items)} width={w * 0.45} height={y(s.items)} fill="var(--water)" opacity={0.8} />
              <rect x={x0 + w * 0.5} y={H - y(s.told)} width={w * 0.5} height={y(s.told)} fill="var(--accent)" opacity={0.55} />
              <rect x={x0 + w * 0.5} y={H - y(s.told) - y(s.bad)} width={w * 0.5} height={y(s.bad)} fill="var(--lie)" />
              {s.changes > 0 && <circle cx={t * bw + bw / 2} cy={5} r={Math.min(4.5, 2 + s.changes / 3)} fill="var(--stale)" />}
              {s.held > 0 && <rect x={t * bw + bw / 2 - 3} y={11} width={6} height={6} fill="var(--gold)" transform={`rotate(45 ${t * bw + bw / 2} 14)`} />}
            </g>
          );
        })}
        <rect x={tick * bw} y={0} width={bw} height={H} fill="none" stroke="var(--ink)" strokeWidth={2} />
      </svg>
      <div className="strip-key">
        <span><i style={c("var(--water)")} />items read</span>
        <span><i style={c("var(--accent)")} />messages</span>
        <span><i style={c("var(--lie)")} />not believed</span>
        <span><i style={c("var(--stale)")} />corrections and trust cuts</span>
        <span><i style={c("var(--gold)")} />actions held</span>
      </div>
    </section>
  );
}
