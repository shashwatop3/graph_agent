import { c } from "../css";
import type { FireWorld, RunEvent, SpaceState } from "../types";

const LABEL: Record<string, string> = { unburnt: "alive", burning: "on fire", burnt: "burnt" };
const LINEAR_LABEL: Record<string, string> = { unburnt: "safe", burning: "on fire", burnt: "lost" };

/** The fields of the Ring Fire game, as the Fire game showed them: the truth no agent sees. */
export function FireBody({ space }: { space: SpaceState }) {
  const w = space.world as unknown as FireWorld;
  const count = (s: string) => w.fields.filter((f) => f.state === s).length;
  const label = w.linear ? LINEAR_LABEL : LABEL;
  const max = w.max_strength ?? 5;
  const stats: [string, string, number][] = w.linear
    ? [
        ["safe", "var(--alive)", count("unburnt")],
        ["on fire", "var(--fire)", count("burning")],
        ["lost", "var(--burnt)", count("burnt")],
        ["water on fire", "var(--water)", Number(space.score.water_on_fire ?? 0)],
        ["water wasted", "var(--lie)", Number(space.score.water_wasted ?? 0)],
      ]
    : [
        ["alive", "var(--alive)", count("unburnt")],
        ["on fire", "var(--fire)", count("burning")],
        ["burnt", "var(--burnt)", count("burnt")],
        ["fields saved", "var(--water)", Number(space.score.fields_saved ?? 0)],
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
      <div className="wtools"><span className="eyebrow">{w.fields.length} fields</span></div>
      <div className="fields">
        {w.fields.map((f) => (
          <div key={f.id} className={`f ${f.state === "unburnt" ? "" : f.state}`} title={`F${f.id}, owned by A${f.owner}: ${label[f.state] ?? f.state}`}>
            <b>F{f.id}{w.linear && f.state === "burning" ? ` · ${f.strength ?? 0}/${max}` : ""}</b>
            <span className="own">A{f.owner} · {label[f.state] ?? f.state}{w.imposters[String(f.owner)] ? " · imposter" : ""}</span>
            {w.linear && f.state === "burning" && (
              <span className="heat" aria-label={`strength ${f.strength ?? 0} of ${max}`}>
                <i style={{ width: `${(100 * (f.strength ?? 0)) / max}%` }} />
              </span>
            )}
          </div>
        ))}
      </div>
      <p className="note">
        {w.linear
          ? `Each tag names the agent that owns the field. Fire arrives at 1 and grows by 1 a day unless watered, which lowers it by 1; at 0 it is out. A field ${max} strong for 2 days is lost.`
          : "Each tag names the agent that owns the field. Fire spreads along the ring; a field watered on the day fire arrives is saved."}
      </p>
    </>
  );
}

export function describeFire(e: RunEvent): string | undefined {
  if (e.kind === "world") {
    const list = (k: string) => ((e[k] as number[] | undefined) ?? []);
    const wasted = list("water_wasted");
    const out = list("extinguished");
    return (
      `the fire: ${list("ignited").length} new fires, watered by ${list("watered").map((a) => `A${a}`).join(", ") || "nobody"}` +
      (out.length ? `; put out at ${out.map((f) => `F${f}`).join(", ")}` : "") +
      (wasted.length ? `; wasted water: ${wasted.map((a) => `A${a}`).join(", ")}` : "")
    );
  }
  return undefined;
}
