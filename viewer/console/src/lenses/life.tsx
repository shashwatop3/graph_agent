import { c } from "../css";
import { str } from "../run/model";
import type { LifeWorld, RunEvent, SpaceState } from "../types";

/** The simulated week: how the run scores, then the calendar, cabs, tasks, cards and mail. */
export function LifeBody({ space }: { space: SpaceState }) {
  const w = space.world as unknown as LifeWorld;
  const checks = space.score.checks ?? {};
  const passed = Object.values(checks).filter(Boolean).length;
  const live = <T extends { deleted?: boolean; cancelled?: boolean; done?: boolean }>(xs: T[]) =>
    xs.filter((x) => !x.deleted && !x.cancelled && !x.done).length;
  const stats: [string, string, string][] = [
    ["checks pass", passed === Object.keys(checks).length ? "var(--ok)" : "var(--stale)", `${passed}/${Object.keys(checks).length}`],
    ["events", "var(--accent)", String(live(w.events))],
    ["cabs booked", "var(--water)", String(live(w.cabs))],
    ["payments", w.payments.length ? "var(--stale)" : "var(--ok)", String(w.payments.length)],
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
      <div className="wtools"><span className="eyebrow">flight now departs {w.departs}</span></div>
      <div className="cols">
        <div>
          <div className="eyebrow">Calendar</div>
          <ul className="bl">{w.events.map((e) => <li key={e.id} className={e.deleted ? "stale" : ""}><span>{e.title}</span><small>{e.start}–{e.end.split(" ")[1]}</small></li>)}</ul>
          <div className="eyebrow">Cabs</div>
          <ul className="bl">{w.cabs.length ? w.cabs.map((x) => <li key={x.id} className={x.cancelled ? "stale" : ""}><span>{x.id} to {x.to}</span><small>{x.pickup}</small></li>) : <li className="none">none</li>}</ul>
          <div className="eyebrow">Tasks</div>
          <ul className="bl">{w.tasks.length ? w.tasks.map((t) => <li key={t.id} className={t.done ? "stale" : ""}><span>{t.title}</span><small>{t.due}</small></li>) : <li className="none">none</li>}</ul>
        </div>
        <div>
          <div className="eyebrow">Subscriptions</div>
          <ul className="bl">{Object.entries(w.subscriptions).map(([s, card]) => <li key={s}><span>{s}</span><small>{card}</small></li>)}</ul>
          <div className="eyebrow">Payments</div>
          <ul className="bl">{w.payments.length ? w.payments.map((x, i) => <li key={i} className="bad"><span>{x.payee}</span><small>{x.amount}</small></li>) : <li className="none">none made</li>}</ul>
          <div className="eyebrow">Mail in</div>
          <ul className="bl mail">{w.mail.map((m) => (
            <li key={m.id} className={m.scam ? "scam" : ""}><span>{m.subject}</span><small>{m.from === "me" ? "sent" : m.from.split("@")[0]}</small></li>
          ))}</ul>
        </div>
      </div>
    </>
  );
}

export function describeLife(e: RunEvent): string | undefined {
  if (e.kind === "extract") return `read ${str(e.item)}: ${(e.claims as unknown[][]).map((x) => x.join(" ")).join("; ") || "no claims"}`;
  return undefined;
}
