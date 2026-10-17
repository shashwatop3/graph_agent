"""Ring Fire experiments on the frame: the same games, scorer and tables as harness/experiment.py.

Systems (name -> store and variant):

    frame-memory            in-memory store, every agent every day (the original game)
    frame-falkor            the same on FalkorDB
    frame-postgres          the same on Postgres
    frame-memory-group      plus group warnings (quorum 1)
    frame-falkor-group
    frame-memory-wake       agents wake only on news or a fire due at their fields
    frame-falkor-wake
    frame-memory-rerouter   plus a responder that links honest agents around exposed liars
    frame-falkor-rerouter

A plain "frame-*" system shows its agents exactly what "graph-*" shows in the original loop, so the
two share a model cache: rerunning an old graph experiment on the frame costs nothing.
"""

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from graph_agent.core.store import Store
from graph_agent.harness.llm import ModelClient
from graph_agent.harness.trace import Trace, TracedClient
from graph_agent.stores.falkor import FalkorStore
from graph_agent.stores.memory import MemoryStore
from graph_agent.stores.postgres import PostgresStore

from ..pack import run_frame_game
from .experiment import Knobs, Row, make_scenario, save
from .scoring import Probe, make_probe_hook, score_game, trace_final_state

STORES: dict[str, type[Store]] = {
    "memory": MemoryStore,
    "falkor": FalkorStore,
    "postgres": PostgresStore,
}
VARIANTS = ("", "group", "wake", "rerouter")


def parse_system(system: str) -> tuple[type[Store], str]:
    parts = system.split("-")
    if parts[0] != "frame" or len(parts) not in (2, 3) or parts[1] not in STORES:
        raise ValueError(f"unknown frame system {system!r}")
    variant = parts[2] if len(parts) == 3 else ""
    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r} in {system!r}")
    return STORES[parts[1]], variant


def run_frame_experiment(
    systems: list[str],
    grid: list[Knobs],
    seeds: list[int],
    client_for: Callable[[str, Knobs], ModelClient],
    *,
    budget: int = 4000,
    probe_days: tuple[int, ...] = (2, 4),
    out_dir: str | Path | None = None,
    log_dir: str | Path | None = None,
    log_contexts: bool = True,
    system_label: Callable[[str], str] = lambda s: s,
) -> list[Row]:
    """One row per (knobs, seed, system), as harness.experiment.run_experiment.

    `system_label(system)` is the name the log records (pass `lambda s: "graph-memory"` to make a
    frame log byte-for-byte comparable with an old one)."""
    rows: list[Row] = []
    for index, knobs in enumerate(grid):
        for seed in seeds:
            scenario = make_scenario(knobs, seed)
            for system in systems:
                store_class, variant = parse_system(system)
                store = store_class()
                log_name = f"{system}_g{index}_n{knobs.n_agents}_s{seed}.jsonl"
                trace = Trace(Path(log_dir) / log_name if log_dir else None, contexts=log_contexts)
                client = TracedClient(client_for(system, knobs), trace)
                probes: list[Probe] = []
                hook = make_probe_hook(client, probes, budget, set(probe_days), trace)
                try:
                    result, view = run_frame_game(
                        scenario,
                        store,
                        client,
                        budget=budget,
                        after_day=hook,
                        trace=trace,
                        quorum=1 if variant == "group" else None,
                        wake=variant == "wake",
                        rerouter=variant == "rerouter",
                        system=system_label(system),
                    )
                    row = score_game(result, view, probes)
                    trace_final_state(trace, result, view, probes, row)
                except BaseException as error:  # also a spend cap (SystemExit) or Ctrl-C
                    trace.emit("aborted", error=f"{type(error).__name__}: {error}")
                    raise
                finally:
                    store.close()
                    trace.close()
                rows.append({"system": system, "seed": seed, **asdict(knobs), **row})
                if out_dir is not None:
                    save(rows, out_dir)
    if out_dir is not None:
        save(rows, out_dir)
    return rows
