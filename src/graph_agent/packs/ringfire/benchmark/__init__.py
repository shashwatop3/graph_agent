"""The Ring Fire benchmark: the original game loop, its memory systems (the graph and the
baselines), scoring, sweeps and the data for the replay and cascade viewers.

Events a Ring Fire run writes to its trace (harness/trace.py): game_start, day_start, turn_start,
model_call, tool_result, action, message, imposter_relay, imposter_lie, turn_end, day_end,
exposure, probe, probe_scored, beliefs, score.
"""
