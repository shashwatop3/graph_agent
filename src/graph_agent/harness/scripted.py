"""Plays a scripted scenario end to end with no LLM: simulator -> adapter -> store.

The scenario scripts what every agent sends. Everything else is the real pipeline (pipeline.py):
messages and evidence are recorded, the adapter's evidence rule decides whom each agent stops
trusting, and `Store.expose` propagates that. We return exactly what it changed.

This is the harness's job because it is the only package allowed to import both the simulator and
the adapter.
"""

from ..core.store import Store
from ..sim.scenario import run_scenario
from .pipeline import Exposure, Pipeline

__all__ = ["Exposure", "play_scripted"]


def play_scripted(scenario: dict, store: Store):
    """Run `scenario` into `store`. Returns (exposures in order, the finished Game)."""
    pipeline = Pipeline(store)
    game = run_scenario(
        scenario,
        on_start=pipeline.start,
        on_send=lambda game, message: pipeline.message(message),
        on_day=pipeline.day,
    )
    return pipeline.exposures, game
