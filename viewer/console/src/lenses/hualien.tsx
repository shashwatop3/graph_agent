import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";

interface QuakeWorld {
  lens: "hualien";
  reports: { id: string; tick: number; source: string; text: string; rumour: boolean }[];
  fabs: { id: string; km: number; early: string; reviewed: string; alert: string | null }[];
  alerts: { id: string; tick: number; fab: string; level: string; withdrawn: boolean }[];
}

const LEVEL: Record<string, string> = { high: "var(--stale)", medium: "var(--accent)", low: "var(--ok)" };

/** The quake: how the run scores, each fab's alert against what the reviewed figures call for,
 *  then every alert sent and every report that has arrived. */
export function QuakeBody({ space }: { space: SpaceState }) {
  const w = space.world as unknown as QuakeWorld;
  const checks = space.score.checks ?? {};
  const passed = Object.values(checks).filter(Boolean).length;
  const rumours = w.reports.filter((r) => r.rumour).length;
  const stats: [string, string, string][] = [
    ["checks pass", passed === Object.keys(checks).length ? "var(--ok)" : "var(--stale)", `${passed}/${Object.keys(checks).length}`],
    ["reports in", "var(--accent)", String(w.reports.length)],
    ["alerts sent", "var(--water)", String(w.alerts.length)],
    ["rumours", rumours ? "var(--stale)" : "var(--ok)", String(rumours)],
  ];
  return (
    <>
      <div className="stats">
        {stats.map(([label, colour, value]) => (
          <div className="stat" key={label}>
            <div className="n">{value}</div>
            <div className="l"><i style={c(colour)} />{label}</div>
          </div>
        ))}
      </div>
      <div className="checks">
        {Object.entries(checks).map(([name, ok]) => (
          <div key={name} className={`check-row ${ok ? "ok" : "bad"}`}><i>{ok ? "✓" : "✕"}</i>{name}</div>
        ))}
      </div>
      <div className="cols">
        <div>
          <div className="eyebrow">Fabs · alert in force (reviewed figures call for)</div>
          <ul className="bl">{w.fabs.map((f) => (
            <li key={f.id} className={f.alert && f.alert !== f.reviewed ? "bad" : ""}>
              <span>{f.id}, {f.km} km</span>
              <small><b style={{ color: LEVEL[f.alert ?? ""] ?? "var(--muted)" }}>{f.alert ?? "none"}</b> ({f.reviewed}{f.early !== f.reviewed ? `, early ${f.early}` : ""})</small>
            </li>
          ))}</ul>
          <div className="eyebrow">Alerts sent</div>
          <ul className="bl">{w.alerts.length ? w.alerts.map((a) => (
            <li key={a.id} className={a.withdrawn ? "stale" : ""}><span>{a.id} {a.fab} at {a.level}</span><small>tick {a.tick}</small></li>
          )) : <li className="none">none yet</li>}</ul>
        </div>
        <div>
          <div className="eyebrow">Reports in</div>
          <ul className="bl mail">{w.reports.map((r) => (
            <li key={r.id} className={r.rumour ? "scam" : ""} title={r.text}><span>{r.text.length > 60 ? `${r.text.slice(0, 58)}…` : r.text}</span><small>{r.source} · tick {r.tick}</small></li>
          ))}</ul>
        </div>
      </div>
    </>
  );
}

export function describeQuake(e: RunEvent): string | undefined {
  void e;
  return undefined; // the quake pack adds no event kinds of its own
}
