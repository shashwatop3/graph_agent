"""Run every system on the same generated games and tabulate the results.

A game is generated from `Knobs` (the scale settings in game.md) and a seed, so the same knobs and
seed give the same world, the same imposters and the same lies for every system. The runner plays
each (knobs, seed, system) combination, scores it (scoring.py) and collects one row per game.

The model is passed in per game (`client_for`), so the same runner serves a free stand-in in tests
and a real cached model for a real experiment.
"""

import csv
import json
import random
import statistics
from collections import defaultdict
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from ..core.store import Store
from ..sim.scenario import ClaimSpec, ImposterSpec, Scenario, SendSpec
from ..stores.falkor import FalkorStore
from ..stores.memory import MemoryStore
from ..stores.postgres import PostgresStore
from .backend import GraphBackend
from .baselines import BASELINES
from .game import run_game
from .llm import ModelClient
from .scoring import Probe, make_probe_hook, score_game, trace_final_state
from .trace import Trace, TracedClient
from .types import Backend


@dataclass(frozen=True)
class Knobs:
    """The scale settings. The defaults are the easy end; each can be turned up."""

    n_agents: int = 8  # also the relay depth: a claim can travel up to n_agents - 1 hops
    fields_per_agent: int = 1
    hidden_edges: int = 0  # paths nobody knows about until fire uses one
    imposters: int = 1  # how many imposters follow `behaviour`
    behaviour: str = "subtle_bias"  # subtle_bias, hide_fire or false_alarm
    colluders: int = 0  # adjacent imposters backing one false alarm, so counting sources is fooled
    extra_links: int = 0  # shortcut links from the start: more routes to the same belief
    water_per_agent: int | None = 2  # waterings each agent has; None = unlimited (water spam wins)
    evidence: str = "private"  # who is shown that fire reached a field: "private" or "public"


def make_scenario(knobs: Knobs, seed: int) -> Scenario:
    """The scenario dict (the format sim/scenario.py reads) for these knobs and this seed."""
    rng = random.Random(seed)
    n = knobs.n_agents
    imposters: list[ImposterSpec] = []
    sends: list[SendSpec] = []
    scenario: Scenario = {
        "seed": seed,
        "evidence": knobs.evidence,
        "rules": {"water_per_agent": knobs.water_per_agent},
        "world": {
            "n_agents": n,
            "fields_per_agent": knobs.fields_per_agent,
            "n_hidden_edges": knobs.hidden_edges,
            "n_initial_fires": 1,
        },
        "imposters": imposters,
        "links": [],
        "sends": sends,
    }
    taken: set[int] = set()
    liars: list[int] = []

    # the colluding block: adjacent agents who all back the same false alarm
    if knobs.colluders:
        start = rng.randrange(n)
        block = [(start + i) % n for i in range(knobs.colluders)]
        taken |= set(block)
        liars += block
        imposters += [ImposterSpec(agent=a, behaviour="false_alarm") for a in block]
    others = rng.sample([a for a in range(n) if a not in taken], knobs.imposters)
    imposters += [ImposterSpec(agent=a, behaviour=knobs.behaviour) for a in others]
    if knobs.behaviour == "false_alarm":
        liars += others

    # the lie: fire "will reach" a field on the far side of the ring, earlier than it really could
    n_fields = n * knobs.fields_per_agent
    lie = ClaimSpec(field_id=n_fields // 2, day=max(1, n_fields // 4))
    for liar in liars:
        for neighbour in ((liar - 1) % n, (liar + 1) % n):
            if neighbour not in liars:
                sends.append(
                    SendSpec(day=1, sender=liar, receiver=neighbour, claim=ClaimSpec(**lie))
                )

    chosen: set[tuple[int, int]] = set()
    while len(chosen) < knobs.extra_links:
        a, b = sorted(rng.sample(range(n), 2))
        if (b - a) % n not in (1, n - 1):  # not already ring neighbours
            chosen.add((a, b))
    scenario["links"] = [list(link) for link in sorted(chosen)]
    return scenario


# ---- the systems ---------------------------------------------------------------------------------


# what a system gives back: its backend, and a function that cleans up after the run
type MadeSystem = tuple[Backend, Callable[[], None]]


def _graph(store_class: type[Store]) -> Callable[[], MadeSystem]:
    def make() -> MadeSystem:
        store = store_class()
        name = f"graph-{store_class.__name__.removesuffix('Store').lower()}"
        return GraphBackend(store, name=name), store.close

    return make


def _baseline(make_backend: Callable[[], Backend]) -> Callable[[], MadeSystem]:
    def make() -> MadeSystem:
        return make_backend(), lambda: None

    return make


# name -> function returning (backend, cleanup)
SYSTEMS: dict[str, Callable[[], MadeSystem]] = {
    "graph-memory": _graph(MemoryStore),
    "graph-falkor": _graph(FalkorStore),
    "graph-postgres": _graph(PostgresStore),
    **{name: _baseline(make_backend) for name, make_backend in BASELINES.items()},
}

# one result row: the system, the seed, every knob, and every metric, by name
Row = dict[str, object]


def run_experiment(
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
) -> list[Row]:
    """One row per (knobs, seed, system). `client_for(system, knobs)` returns the model to use.

    With `log_dir`, every game writes a detailed log there (see trace.py), and the results so far
    are saved after each game, so a run that is stopped part-way keeps what it finished."""
    rows: list[Row] = []
    for index, knobs in enumerate(grid):
        for seed in seeds:
            scenario = make_scenario(knobs, seed)
            for system in systems:
                backend, cleanup = SYSTEMS[system]()
                log_name = f"{system}_g{index}_n{knobs.n_agents}_s{seed}.jsonl"
                trace = Trace(Path(log_dir) / log_name if log_dir else None, contexts=log_contexts)
                client = TracedClient(client_for(system, knobs), trace)
                probes: list[Probe] = []
                hook = make_probe_hook(client, probes, budget, set(probe_days), trace)
                try:
                    result = run_game(
                        scenario, backend, client, budget=budget, after_day=hook, trace=trace
                    )
                    row = score_game(result, backend, probes)
                    trace_final_state(trace, result, backend, probes, row)
                except BaseException as error:  # also a spend cap (SystemExit) or Ctrl-C
                    trace.emit("aborted", error=f"{type(error).__name__}: {error}")
                    raise
                finally:
                    cleanup()
                    trace.close()
                rows.append({"system": system, "seed": seed, **asdict(knobs), **row})
                if out_dir is not None:
                    save(rows, out_dir)
    if out_dir is not None:
        save(rows, out_dir)
    return rows


# ---- tables and plots ----------------------------------------------------------------------------

KNOB_NAMES = list(Knobs.__dataclass_fields__)
DEFAULT_METRICS = [
    "fields_saved",
    "water_wasted",
    "lies_relayed",
    "false_beliefs_remaining",
    "propagation_precision",
    "propagation_recall",
    "probe_accuracy",
    "stale_leakage",
    "tokens_in",
    "model_calls",
]


def save(rows: list[Row], out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(rows, indent=1, sort_keys=True))
    columns = sorted({k for r in rows for k in r})
    with (out / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, columns)
        writer.writeheader()
        writer.writerows(rows)
    (out / "summary.md").write_text(summary_table(rows))


def _mean_range(values: list[object]) -> str:
    numbers = [v for v in values if isinstance(v, int | float)]
    if not numbers:
        return "n/a"
    low, high = min(numbers), max(numbers)
    mean = statistics.mean(numbers)
    return f"{mean:.2f}" if low == high else f"{mean:.2f} ({low:.2f}-{high:.2f})"


def summary_table(rows: list[Row], metrics: list[str] | None = None) -> str:
    """Markdown: one block per knob setting, one row per system, mean (min-max) over seeds."""
    metrics = metrics or DEFAULT_METRICS
    by_knobs: dict[tuple[object, ...], dict[str, list[Row]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        by_knobs[tuple(row[k] for k in KNOB_NAMES)][str(row["system"])].append(row)
    seeds = len({r["seed"] for r in rows})
    out: list[str] = []
    for knob_values, systems in by_knobs.items():
        out.append(
            "### " + ", ".join(f"{k}={v}" for k, v in zip(KNOB_NAMES, knob_values, strict=True))
        )
        out.append("")
        out.append("| system | " + " | ".join(metrics) + " |")
        out.append("|---|" + "---|" * len(metrics))
        for system, group in systems.items():
            cells = [_mean_range([r.get(m) for r in group]) for m in metrics]
            out.append(f"| {system} | " + " | ".join(cells) + " |")
        out.append("")
    out.append(f"Mean (min-max) over {seeds} seed(s). The sample is small: read ranges, not means.")
    return "\n".join(out) + "\n"


def plot_svg(rows: list[Row], x: str, y: str, title: str = "") -> str:
    """A standalone SVG line chart of metric `y` against knob `x`, one line per system (mean over
    seeds). Pure Python so there is nothing to install."""
    series: dict[str, dict[float, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        x_value, y_value = row.get(x), row.get(y)
        if isinstance(x_value, int | float) and isinstance(y_value, int | float):
            series[str(row["system"])][x_value].append(y_value)
    points = {s: sorted((xv, statistics.mean(v)) for xv, v in d.items()) for s, d in series.items()}
    xs = sorted({xv for p in points.values() for xv, _ in p})
    ys = [yv for p in points.values() for _, yv in p]
    if not xs or not ys:
        return "<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>"
    low, high = min(0, min(ys)), max(ys) or 1
    left, top, width, height = 50, 30, 520, 260

    def px(v: float) -> float:
        return left + (width * (v - xs[0]) / ((xs[-1] - xs[0]) or 1))

    def py(v: float) -> float:
        return top + height - height * (v - low) / ((high - low) or 1)

    colours = ["#1b6ef3", "#d9480f", "#2b8a3e", "#862e9c", "#e67700", "#0b7285", "#495057"]
    parts = [
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"viewBox='0 0 {left + width + 150} {top + height + 40}' "
        "font-family='sans-serif' font-size='12'>",
        f"<text x='{left}' y='18' font-weight='bold'>{title or y + ' by ' + x}</text>",
        f"<line x1='{left}' y1='{top + height}' x2='{left + width}' y2='{top + height}' "
        "stroke='#888'/>",
        f"<line x1='{left}' y1='{top}' x2='{left}' y2='{top + height}' stroke='#888'/>",
        f"<text x='{left - 6}' y='{top + 4}' text-anchor='end'>{high:g}</text>",
        f"<text x='{left - 6}' y='{top + height}' text-anchor='end'>{low:g}</text>",
    ]
    for xv in xs:
        parts.append(
            f"<text x='{px(xv)}' y='{top + height + 16}' text-anchor='middle'>{xv:g}</text>"
        )
    for i, (system, pts) in enumerate(sorted(points.items())):
        colour = colours[i % len(colours)]
        path = " ".join(f"{px(a):.1f},{py(b):.1f}" for a, b in pts)
        parts.append(f"<polyline points='{path}' fill='none' stroke='{colour}' stroke-width='2'/>")
        parts += [
            f"<circle cx='{px(a):.1f}' cy='{py(b):.1f}' r='3' fill='{colour}'/>" for a, b in pts
        ]
        parts.append(
            f"<rect x='{left + width + 14}' y='{top + 16 * i}' width='10' height='10' "
            f"fill='{colour}'/>"
        )
        parts.append(f"<text x='{left + width + 30}' y='{top + 16 * i + 9}'>{system}</text>")
    parts.append("</svg>")
    return "".join(parts)
