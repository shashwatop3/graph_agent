import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";

interface Booked { id: string; cancelled: boolean }
interface OffsiteWorld {
  lens: "offsite";
  truth: { day: string; travel_day: string; coming: string[]; budget: number; final_budget: number };
  trips: (Booked & { person: string; origin: string; depart: string })[];
  rooms: (Booked & { night: string; rooms: number })[];
  catering: (Booked & { day: string; meals: number })[];
  invites: (Booked & { day: string; attendees: string[] })[];
  agenda: Record<string, string>;
  sent: { id: string; tick: number; to: string; subject: string; body: string }[];
  payments: { tick: number; payee: string; amount: number }[];
  mail: { id: string; tick: number; from: string; subject: string; scam: boolean }[];
}

/** The offsite: how the run scores, what is booked now against what the facts call for, and the
 *  mail that came in. Cancelled bookings stay listed, struck through, so the churn is visible. */
export function OffsiteBody({ space }: { space: SpaceState }) {
  const w = space.world as unknown as OffsiteWorld;
  const t = w.truth;
  const checks = space.score.checks ?? {};
  const passed = Object.values(checks).filter(Boolean).length;
  const outward = Number(space.score.outward_actions ?? 0);
  const stats: [string, string, string][] = [
    ["checks pass", passed === Object.keys(checks).length ? "var(--ok)" : "var(--stale)", `${passed}/${Object.keys(checks).length}`],
    ["actions taken", "var(--accent)", String(outward)],
    ["held", "var(--gold)", String(space.score.held_actions ?? 0)],
    ["payments", w.payments.length ? "var(--stale)" : "var(--ok)", String(w.payments.length)],
  ];
  const row = (x: Booked, label: string, detail: string, wrong: boolean) => (
    <li key={x.id} className={x.cancelled ? "stale" : wrong ? "bad" : ""}><span>{label}</span><small>{detail}</small></li>
  );
  const none = <li className="none">none</li>;
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
      <div className="wtools">
        <span className="eyebrow">
          the facts now: offsite {t.day}, travel {t.travel_day} 16:00, {t.coming.length} coming, budget {t.budget}
        </span>
      </div>
      <div className="cols">
        <div>
          <div className="eyebrow">Trips</div>
          <ul className="bl">{w.trips.length ? w.trips.map((x) =>
            row(x, `${x.person} from ${x.origin}`, x.depart, !t.coming.includes(x.person) || !x.depart.startsWith(t.travel_day)),
          ) : none}</ul>
          <div className="eyebrow">Rooms · catering · invite</div>
          <ul className="bl">
            {w.rooms.map((x) => row(x, `${x.rooms} rooms`, `${x.night} night`, x.night !== t.travel_day || x.rooms !== t.coming.length))}
            {w.catering.map((x) => row(x, `${x.meals} meals`, x.day, x.day !== t.day || x.meals !== t.coming.length))}
            {w.invites.map((x) => row(x, `invite: ${x.attendees.join(", ")}`, x.day, x.day !== t.day))}
            {!w.rooms.length && !w.catering.length && !w.invites.length && none}
          </ul>
        </div>
        <div>
          <div className="eyebrow">Agenda</div>
          <ul className="bl">{Object.entries(w.agenda).map(([s, owner]) => (
            <li key={s}><span>{s.replace("sess-", "")}</span><small>{owner}</small></li>
          ))}</ul>
          <div className="eyebrow">Budget sent to finance</div>
          <ul className="bl">{w.sent.length ? w.sent.map((s) => (
            <li key={s.id}><span>{s.body}</span><small>tick {s.tick}</small></li>
          )) : none}</ul>
          <div className="eyebrow">Mail in</div>
          <ul className="bl mail">{w.mail.map((m) => (
            <li key={m.id} className={m.scam ? "scam" : ""}><span>{m.subject}</span><small>{m.from.split("@")[0]}</small></li>
          ))}</ul>
        </div>
      </div>
    </>
  );
}

export function describeOffsite(e: RunEvent): string | undefined {
  void e;
  return undefined; // the offsite pack adds no event kinds of its own
}
