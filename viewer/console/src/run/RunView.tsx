import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, follow } from "../api";
import type { Live } from "../Graph";
import { layout } from "../layout";
import type { NodeKind, RunEvent, SpaceState, Why } from "../types";
import { distrustAt, nextTick, quarantinedBy, str, trailOf } from "./model";
import { Network } from "./Network";
import { Side } from "./Side";
import { Timeline } from "./Timeline";

interface Selection {
  node: string | null;
  belief: string | null; // the belief whose chain is open in the node's card
}

/** A run, laid out like the Fire game: the timeline on top, the team network with a floating card
 * for the open node, and a separate side screen with the state of things. */
export function RunView({ spaceId, onBack }: { spaceId: string; onBack: () => void }) {
  const [space, setSpace] = useState<SpaceState | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [shown, setShown] = useState<number | null>(null); // null: follow the latest tick
  const [sel, setSel] = useState<Selection>({ node: null, belief: null });
  const [why, setWhy] = useState<Why | null>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const refresh = useRef<number | null>(null);

  const load = useCallback(
    () => api.state(spaceId).then(setSpace).catch((e: Error) => setError(e.message)),
    [spaceId],
  );

  useEffect(() => {
    void load();
    const seen: RunEvent[] = [];
    const stop = follow(spaceId, 0, (event) => {
      seen.push(event);
      setEvents([...seen]);
      if (refresh.current === null) {
        refresh.current = window.setTimeout(() => { refresh.current = null; void load(); }, 350);
      }
    });
    return () => { stop(); if (refresh.current !== null) window.clearTimeout(refresh.current); };
  }, [spaceId, load]);

  const last = Math.max(0, (space?.tick ?? 1) - 1);
  const tick = Math.min(shown ?? last, last);
  const setTick = useCallback((t: number) => setShown(Math.max(0, Math.min(last, t))), [last]);

  // the open belief's chain, from the server (it changes as the run goes on)
  useEffect(() => {
    if (!sel.node || !sel.belief) {
      setWhy(null);
      return;
    }
    let cancelled = false;
    api.why(spaceId, sel.node, sel.belief).then((w) => { if (!cancelled) setWhy(w); }).catch(() => setWhy(null));
    return () => { cancelled = true; };
  }, [spaceId, sel.node, sel.belief, space?.events]);

  // replay the ticks already played, one every two seconds
  useEffect(() => {
    if (!playing) return;
    if (tick >= last) {
      setPlaying(false);
      return;
    }
    const t = window.setTimeout(() => setShown(tick + 1), 1800);
    return () => window.clearTimeout(t);
  }, [playing, tick, last]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === "INPUT") return;
      if (e.key === "Escape") setSel({ node: null, belief: null });
      if (e.key === "ArrowRight") { setPlaying(false); setTick(tick + 1); }
      if (e.key === "ArrowLeft") { setPlaying(false); setTick(tick - 1); }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [tick, setTick]);

  const positions = useMemo(() => (space ? layout(space.team) : {}), [space?.team]);
  const kinds = useMemo(
    () => Object.fromEntries((space?.nodes ?? []).map((n) => [n.type, n.kind])) as Record<string, NodeKind>,
    [space?.nodes],
  );

  const live: Live | undefined = useMemo(() => {
    if (!space) return undefined;
    const quarantine = quarantinedBy(events, tick);
    const here = events.filter((e) => e.tick === tick);
    const team = new Set(space.nodes.map((n) => n.id));
    return {
      active: new Set(here.filter((e) => e.kind === "turn").map((e) => str(e.node))),
      waiting: new Set(space.nodes.filter((n) => n.pending.length).map((n) => n.id)),
      held: new Set(
        space.proposals.filter((p) => (p.status === "held" || p.status === "reviewed") && p.tick <= tick).map((p) => p.node),
      ),
      messages: here.filter((e) => e.kind === "message").map((e) => ({
        src: str(e.sender),
        dst: str(e.receiver),
        bad: !e.believed,
        label: `${str(e.subject)}: ${str(e.value)}`.slice(0, 34),
      })),
      items: here
        .filter((e) => e.kind === "item" && !team.has(str(e.source)))
        .flatMap((e) => ((e.to as string[]) ?? []).map((dst) => ({ src: str(e.source), dst }))),
      links: space.links,
      outside: space.outside.map((o) => ({
        id: o.id,
        quarantined: (quarantine.get(o.id)?.size ?? 0) > 0,
        active: here.some((e) => e.kind === "item" && e.source === o.id),
      })),
      cuts: distrustAt(events, tick).filter((c) => team.has(c.agent)),
    };
  }, [space, events, tick]);

  if (error) return <p className="load-error">{error} <button className="linkish" onClick={onBack}>Back</button></p>;
  if (!space || !live) return <p className="none pad">Connecting…</p>;

  const act = async (what: "step" | "play" | "pause") => {
    try {
      setShown(null);
      setPlaying(false);
      await (what === "step" ? api.step(spaceId) : what === "play" ? api.play(spaceId) : api.pause(spaceId));
      await load();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const jump = (pred: (e: RunEvent) => boolean) => {
    setPlaying(false);
    const t = nextTick(events, tick, last, pred);
    if (t !== null) setShown(t);
  };
  const open = (node: string | null, belief: string | null = null) => setSel({ node, belief });
  const heldSoFar = new Set(events.filter((e) => e.kind === "held" && e.tick <= tick).map((e) => str(e.id))).size;
  const quarantined = live.outside.filter((o) => o.quarantined).length;
  const score = space.score;
  const checks = Object.values(score.checks ?? {});

  return (
    <div className="runview">
      <div className="runhead">
        <button className="btn" onClick={onBack} aria-label="Back to the canvas">← Canvas</button>
        <div className="title">
          <div className="eyebrow">
            {space.pack} · {space.model} · {space.store}
            {space.running ? " · running" : space.finished ? " · finished" : " · paused"}
          </div>
          <h2>{space.title}</h2>
        </div>
        <div className="scores">
          {checks.length > 0 && <span className="score"><b>{checks.filter(Boolean).length}/{checks.length}</b> checks</span>}
          {score.unsafe_proposals !== undefined && (
            <span className={`score ${Number(score.unsafe_proposals) ? "bad" : ""}`}><b>{str(score.unsafe_proposals)}</b> unsafe</span>
          )}
          {score.fields_saved !== undefined && <span className="score"><b>{str(score.fields_saved)}/{str(score.fields)}</b> {score.water_on_fire !== undefined ? "honest fields safe" : "fields saved"}</span>}
          {score.water_on_fire !== undefined && <span className="score"><b>{str(score.water_on_fire)}</b> water on fire</span>}
          {score.water_wasted !== undefined && <span className={`score ${Number(score.water_wasted) ? "bad" : ""}`}><b>{str(score.water_wasted)}</b> wasted</span>}
          <span className="score"><b>{space.exposures.length}</b> distrusts</span>
          <span className="score"><b>{Math.round(Number(score.tokens_in ?? 0) / 1000)}k</b> tokens</span>
        </div>
        {space.error && <span className="err">{space.error}</span>}
      </div>

      <Timeline
        space={space}
        events={events}
        tick={tick}
        last={last}
        playing={playing}
        onTick={(t) => { setPlaying(false); setTick(t); }}
        onPlay={() => {
          if (playing) return setPlaying(false);
          if (tick >= last) setShown(0);
          setPlaying(true);
        }}
        onStep={() => void act("step")}
        onRun={() => void act("play")}
        onPause={() => void act("pause")}
        onNextCorrection={() => jump((e) => e.kind === "exposure" || e.kind === "reinstatement" || (e.kind === "change" && str(e.reason).includes("withdrew")))}
        onNextHeld={() => jump((e) => e.kind === "held")}
      />

      <div className="main">
        <Network
          space={space}
          events={events}
          tick={tick}
          positions={positions}
          kinds={kinds}
          live={live}
          trail={trailOf(why, tick)}
          selected={sel.node}
          belief={sel.belief}
          why={why}
          onSelect={open}
          heldSoFar={heldSoFar}
          quarantined={quarantined}
        />
        <Side
          space={space}
          events={events}
          tick={tick}
          onDecide={(id: string, ok: boolean) => void api.decide(spaceId, id, ok).then(load)}
          onOpen={(node: string) => open(node)}
        />
      </div>
    </div>
  );
}
