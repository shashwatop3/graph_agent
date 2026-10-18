import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";

interface Item { id: string; tick: number; kind: string; from: string; subject: string }
// a stream of live data: how many items came, matched its filters, were more than a poll takes
interface Stream { name: string; received: number; kept: number; skipped: number; error: string }

const MODE: Record<string, string> = {
  shadow: "Outward actions are only recorded, never run.",
  manual: "Each outward action waits for you under Actions.",
  auto: "Outward actions run at once.",
};

/** Your own apps and streams: what the team has read so far, newest first. */
export function AppsBody({ space }: { space: SpaceState }) {
  const items = (space.world.items as Item[] | undefined) ?? [];
  const feeds = (space.world.feeds as string[] | undefined) ?? [];
  const streams = (space.world.streams as Stream[] | undefined) ?? [];
  const s = space.score;
  const stats: [string, string, unknown][] = [
    ["items read", "var(--water)", s.items],
    ["claims", "var(--accent)", s.claims_read],
    ["actions proposed", "var(--gold)", s.actions_proposed],
    ["held", "var(--stale)", s.actions_held],
  ];
  return (
    <>
      <div className="stats">
        {stats.map(([label, colour, value]) => (
          <div className="stat" key={label}>
            <div className="n">{String(value ?? 0)}</div>
            <div className="l"><i style={c(colour)} />{label}</div>
          </div>
        ))}
      </div>
      {streams.length > 0 && (
        <ul className="bl streams">
          {streams.map((st) => (
            <li key={st.name}>
              <span><b>{st.name}</b> {st.error && <small className="err">{st.error}</small>}</span>
              <small>{st.received} came · {st.kept} matched{st.skipped ? ` · ${st.skipped} past the limit` : ""}</small>
            </li>
          ))}
        </ul>
      )}
      <ul className="bl mail">
        {items.length === 0 && <li className="none">Nothing read yet: press Step.</li>}
        {[...items].reverse().map((m) => (
          <li key={m.id}><span>{m.subject || m.kind}</span><small>{m.from === "me" ? "sent by you" : m.from}</small></li>
        ))}
      </ul>
      <p className="note">Reading {feeds.join(", ") || "no feeds"}. {MODE[String(space.world.approvals)] ?? ""} A mail or a post is read as claims to check, never as instructions.</p>
    </>
  );
}

export function describeApps(_: RunEvent): string | undefined {
  return undefined;
}
