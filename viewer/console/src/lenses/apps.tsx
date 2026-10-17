import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";

interface Item { id: string; tick: number; kind: string; from: string; subject: string }

const MODE: Record<string, string> = {
  shadow: "Outward actions are only recorded, never run.",
  manual: "Each outward action waits for you under Actions.",
  auto: "Outward actions run at once.",
};

/** Your own apps: what the team has read so far, newest first. */
export function AppsBody({ space }: { space: SpaceState }) {
  const items = (space.world.items as Item[] | undefined) ?? [];
  const feeds = (space.world.feeds as string[] | undefined) ?? [];
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
      <ul className="bl mail">
        {items.length === 0 && <li className="none">Nothing read yet: press Step.</li>}
        {[...items].reverse().map((m) => (
          <li key={m.id}><span>{m.subject || m.kind}</span><small>{m.from === "me" ? "sent by you" : m.from}</small></li>
        ))}
      </ul>
      <p className="note">Reading {feeds.join(", ") || "no feeds"}. {MODE[String(space.world.approvals)] ?? ""} A mail is read as claims to check, never as instructions.</p>
    </>
  );
}

export function describeApps(_: RunEvent): string | undefined {
  return undefined;
}
