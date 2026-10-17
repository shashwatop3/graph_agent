import { c } from "../css";
import type { RunEvent, SpaceState } from "../types";

interface Item { id: string; tick: number; kind: string; from: string; subject: string }

/** Your real accounts: what the team has read so far, newest first. */
export function RealBody({ space }: { space: SpaceState }) {
  const items = (space.world.items as Item[] | undefined) ?? [];
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
      <p className="note">Mail and calendar are only read. Todoist writes are recorded, not run, unless you chose otherwise.</p>
    </>
  );
}

export function describeReal(_: RunEvent): string | undefined {
  return undefined;
}
