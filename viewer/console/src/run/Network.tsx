import { useLayoutEffect, useRef, useState } from "react";
import { c } from "../css";
import { Graph, type Live, type TrailStep } from "../Graph";
import { isRing, type Positions, R, W } from "../layout";
import type { NodeKind, RunEvent, SpaceState, Why } from "../types";
import { AgentCard } from "./AgentCard";

interface Props {
  space: SpaceState;
  events: RunEvent[];
  tick: number;
  positions: Positions;
  kinds: Record<string, NodeKind>;
  live: Live;
  trail: TrailStep[];
  selected: string | null;
  belief: string | null;
  why: Why | null;
  onSelect: (node: string | null, belief?: string | null) => void;
  heldSoFar: number;
  quarantined: number;
}

/** The team: who told whom at this tick, trust cuts, the open belief's trail, and the open node's
 * card floating beside it, as in the Fire game. */
export function Network(p: Props) {
  const { space, tick, positions, selected } = p;
  const box = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ left: number; top: number } | null>(null);

  // place the card beside the open node, on the side with more room
  useLayoutEffect(() => {
    if (selected === null || !box.current || !card.current) return setPlace(null);
    const b = box.current.getBoundingClientRect();
    const scale = b.width / W;
    const [x, y] = positions[selected] ?? [W / 2, 300];
    const w = Math.min(390, b.width - 24);
    const gap = (R + 14) * scale;
    let left = x * scale > b.width / 2 ? x * scale - w - gap : x * scale + gap;
    left = Math.max(12, Math.min(left, b.width - w - 12));
    const top = Math.max(12, Math.min(y * scale - 70, b.height - card.current.offsetHeight - 12));
    setPlace({ left, top });
  }, [selected, tick, p.belief, p.why, positions]);

  return (
    <section className="panel">
      <div className="ph">
        <div>
          <div className="eyebrow">What the nodes tell each other · each one's only memory is the graph</div>
          <h2>Team network</h2>
        </div>
        <span className="eyebrow">click a node</span>
      </div>
      <div className="net" ref={box}>
        <Graph
          team={space.team}
          positions={positions}
          kinds={p.kinds}
          selected={selected}
          onSelect={(id) => p.onSelect(id, null)}
          live={p.live}
          trail={p.trail}
          centre={isRing(space.team) ? space.clocks[tick] ?? `tick ${tick}` : undefined}
        />
        <div className={`counter ${space.outside.length ? "right" : ""}`}>
          <span className="n" style={c(p.heldSoFar ? "var(--gold)" : "var(--ok)")}>{p.heldSoFar}</span>
          <span className="l">actions held because what they rested on changed</span>
          {p.quarantined > 0 && (
            <>
              <span className="n small" style={c("var(--lie)")}>{p.quarantined}</span>
              <span className="l">senders quarantined</span>
            </>
          )}
        </div>
        {selected !== null && (
          <AgentCard
            ref={card}
            style={place ?? { visibility: "hidden" }}
            space={space}
            events={p.events}
            node={selected}
            tick={tick}
            belief={p.belief}
            why={p.why}
            onBelief={(b) => p.onSelect(selected, b)}
            onOpen={(n, b) => p.onSelect(n, b)}
            onClose={() => p.onSelect(null)}
          />
        )}
      </div>
      <div className="legend">
        <span><i style={c("var(--water)")} />item: sender → stream → router → owner</span>
        <span><i className="o" style={c("var(--water)")} />stream or router passed items on</span>
        <span><i style={c("var(--accent)")} />message believed</span>
        <span><i style={c("var(--lie)")} />not believed</span>
        <span><i style={c("var(--stale)")} />trust cut</span>
        <span><i className="o" style={c("var(--ink)")} />node · filled = took a turn</span>
        <span><i className="o d" style={c("var(--gold)")} />action held</span>
        <span><i style={c("var(--gold)", { height: 5, opacity: 0.7 })} />open belief's trail</span>
      </div>
    </section>
  );
}
