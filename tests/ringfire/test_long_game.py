"""The long game: fields regrow, fires start at random, saboteurs time their lies, a cooldown on
water, and a fixed horizon. Truth, the evidence rule, scoring and the role card must all cope with
a field that burns more than once."""

import pytest
from fake_agent import honest_agent
from fake_baseline_agent import log_reader

from graph_agent.core.model import Belief
from graph_agent.core.registry import Predicate, contradicts
from graph_agent.packs.ringfire import adapter as ringfire
from graph_agent.packs.ringfire.benchmark.backend import GraphBackend
from graph_agent.packs.ringfire.benchmark.baselines import SharedLogBackend
from graph_agent.packs.ringfire.benchmark.experiment import Knobs, make_scenario, run_experiment
from graph_agent.packs.ringfire.benchmark.pipeline import Pipeline, episode, outlook
from graph_agent.packs.ringfire.benchmark.scoring import Probe, probe_truth
from graph_agent.packs.ringfire.sim.comms import Behaviour, Claim, Imposter
from graph_agent.packs.ringfire.sim.fire import FireRules
from graph_agent.packs.ringfire.sim.game import Game
from graph_agent.packs.ringfire.sim.oracle import Oracle
from graph_agent.packs.ringfire.sim.saboteur import planned_lies, projected_arrivals
from graph_agent.packs.ringfire.sim.scenario import build_game
from graph_agent.packs.ringfire.sim.world import Edge, World, WorldConfig
from graph_agent.stores.memory import MemoryStore

LONG = FireRules(burn_days=2, regrow_days=2, water_cooldown=2)


def ring_game(n=6, horizon=13, rules=LONG, imposters=(), random_ignitions=()) -> Game:
    """n agents with one field each on a ring of one-day edges, fire starting at F0."""
    config = WorldConfig(n_agents=n, fields_per_agent=1, n_hidden_edges=0, horizon=horizon)
    world = World(
        config=config,
        seed=0,
        edges=tuple(Edge(i, (i + 1) % n, 1) for i in range(n)),
        initial_fires=((0, 1.0),),
        random_ignitions=tuple(random_ignitions),
    )
    return Game(world, rules, imposters, private_evidence=True)


def play(game: Game, days: int, watering=None) -> None:
    for _ in range(days):
        game.step((watering or {}).get(game.day, set()))


# ---- the contradiction rule -------------------------------------------------------------------


def arrival(belief_id: str, day: int) -> Belief:
    return Belief(id=belief_id, owner="A1", subject="F3", predicate=ringfire.ARRIVAL, value=day)


def test_two_days_further_apart_than_an_episode_are_two_fires_not_a_contradiction():
    predicates = ringfire.predicates(episode=4)
    assert contradicts(arrival("B1", 3), arrival("B2", 7), predicates)  # 4 apart: same fire
    assert not contradicts(arrival("B1", 3), arrival("B2", 8), predicates)  # 5 apart: a new fire
    single = ringfire.predicates()
    assert contradicts(arrival("B1", 3), arrival("B2", 30), single)  # a field that never regrows


def test_separate_beyond_leaves_the_tolerance_alone():
    near = {"p": Predicate(name="p", tolerance=1, separate_beyond=10)}
    a, b = arrival("B1", 3).model_copy(update={"predicate": "p"}), arrival("B2", 4)
    assert not contradicts(a, b.model_copy(update={"predicate": "p"}), near)


# ---- ground truth -----------------------------------------------------------------------------


def test_a_claim_about_the_second_fire_at_a_field_is_true():
    game = ring_game()
    play(game, 13)
    oracle = Oracle(game)
    assert game.sim.fields[0].ignitions == [0, 6, 12]
    assert oracle.claim_is_true(Claim(0, 6)) and oracle.claim_is_true(Claim(0, 12))
    assert oracle.claim_is_true(Claim(0, 5)) is False
    assert oracle.next_ignition(0, after=0) == 6 and oracle.next_ignition(0, after=12) is None


def test_a_claim_about_a_day_after_the_horizon_is_never_settled():
    game = ring_game(horizon=5)
    play(game, 5)
    assert game.sim.finished
    assert Oracle(game).claim_is_true(Claim(3, 9)) is None


def test_a_probe_is_scored_against_the_next_fire_after_the_question():
    game = ring_game()
    play(game, 13)
    assert probe_truth(game, Probe(day=4, agent=0, field_id=0, answer=6)) == 6
    assert probe_truth(game, Probe(day=12, agent=0, field_id=0, answer=6)) == "never"


# ---- the evidence rule with fields that burn again ----------------------------------------------


def told(pipeline: Pipeline, game: Game, sender: int, receiver: int, field: int, day: int):
    message = game.send(sender, receiver, Claim(field, day))
    assert message is not None
    pipeline.message(message)


def test_a_true_claim_about_the_next_fire_is_not_refuted_by_the_last_one():
    game = ring_game()
    pipeline = Pipeline(MemoryStore())
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    for _ in range(3):  # A0 sees F0 burn on day 0 (its own field)
        pipeline.day(game, game.step())
    told(pipeline, game, 1, 0, 0, 6)  # A1 rightly says the fire comes back to F0 on day 6
    for _ in range(4):
        pipeline.day(game, game.step())
    assert game.sim.fields[0].ignitions == [0, 6]
    assert [e.agent for e in pipeline.exposures if e.viewer == "A0"] == []


def test_a_claim_a_day_off_for_the_same_fire_is_still_refuted():
    game = ring_game()
    pipeline = Pipeline(MemoryStore())
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    for _ in range(3):
        pipeline.day(game, game.step())
    told(pipeline, game, 1, 0, 0, 7)  # wrong: the fire is back on day 6
    for _ in range(4):
        pipeline.day(game, game.step())
    assert [(e.viewer, e.agent) for e in pipeline.exposures] == [("A0", "A1")]


def test_the_episode_is_burning_plus_regrowing():
    assert episode(ring_game()) == 4
    assert episode(ring_game(rules=FireRules())) is None


# ---- saboteurs --------------------------------------------------------------------------------


def test_the_projection_follows_the_fire_from_where_it_is_now():
    game = ring_game(n=8, horizon=20)
    play(game, 2)  # F0, F1 burning; F2 is next, on day 2
    projected = projected_arrivals(game)
    assert projected[2] == 2 and projected[5] == 5 and 1 not in projected


def test_a_saboteur_tells_each_honest_neighbour_the_day_before_the_real_fire_once():
    game = ring_game(n=8, horizon=20, imposters=(Imposter(4, Behaviour.SABOTEUR),))
    play(game, 1)  # day 1: fire reaches F3 on day 3 and F5 on day 5
    already: set[tuple[int, int, int]] = set()
    assert planned_lies(game, 4, already) == [(3, Claim(3, 2))]  # F3 is 2 days away
    assert planned_lies(game, 4, already) == []  # not twice
    play(game, 2)  # day 3: F5 is 2 days away
    assert planned_lies(game, 4, already) == [(5, Claim(5, 4))]


def test_a_saboteur_relays_every_claim_a_day_early_and_its_own_lies_are_marked():
    game = ring_game(n=8, imposters=(Imposter(4, Behaviour.SABOTEUR),))
    first = game.send(3, 4, Claim(6, 6))
    relayed = game.send(4, 5, Claim(6, 6), first)
    own = game.send(4, 5, Claim(5, 4))
    assert relayed is not None and relayed.claim == Claim(6, 5) and relayed.altered_by == (4,)
    assert own is not None and own.altered_by == (4,)


def test_a_wasted_watering_leaves_the_owner_unable_to_water_when_the_fire_comes():
    game = ring_game(n=8, horizon=20)
    play(game, 4, watering={3: {4}})  # A4 believed "day 3" (the fire really reaches F4 on day 4)
    assert not game.sim.can_water_today(4)  # day 4: still resting
    play(game, 1)
    assert game.sim.fields[4].ignitions == [4]


# ---- what agents are told ---------------------------------------------------------------------


def test_the_role_card_states_the_long_game_rules():
    card = ringfire.role_card(
        "A1", 8, (1,), cooldown=2, regrow_days=2, random_fires=True, horizon=15, saboteurs=True
    )
    assert "wait 2 days" in card and "grows back 2 days" in card
    assert "start at random" in card and "lasts 15 days" in card
    assert "as many fields burn as possible" in card


def test_the_role_card_of_the_one_fire_game_is_unchanged():
    card = ringfire.role_card("A1", 8, (1,), water=2)
    assert "You cannot water on two days in a row. You have only 2 waterings" in card
    assert "grows back" not in card and "Some agents lie. Messages" in card


def test_graph_and_log_agents_are_told_the_same_rules():
    scenario = make_scenario(Knobs(n_agents=6, water_per_agent=1), 0)
    graph, log = GraphBackend(MemoryStore()), SharedLogBackend()
    graph.start(build_game(scenario))
    log.start(build_game(scenario))
    card = graph.context(1, 0, 4000).split("## Role\n")[1].split("\n")[0]
    assert "only 1 waterings" in card
    assert card in log.context(1, 0, 4000)


# ---- a whole game from knobs ------------------------------------------------------------------

LONG_KNOBS = Knobs(
    n_agents=8,
    imposters=1,
    colluders=2,
    behaviour="saboteur",
    water_per_agent=None,
    water_cooldown=2,
    horizon=12,
    random_fire_chance=0.4,
    regrow_days=2,
)


def test_saboteurs_get_no_scripted_lie_and_the_whole_block_sabotages():
    scenario = make_scenario(LONG_KNOBS, 0)
    assert scenario.get("sends") == []
    assert {i["behaviour"] for i in scenario.get("imposters", [])} == {"saboteur"}
    assert len(scenario.get("imposters", [])) == 3
    game = build_game(scenario)
    assert game.sim.world.config.horizon == 12 and game.sim.world.random_ignitions


@pytest.fixture(scope="module")
def long_rows():
    def stand_in(system, knobs):
        if system.startswith("graph"):
            return honest_agent(knobs.n_agents)
        return log_reader(knobs.n_agents)

    systems = ["graph-memory", "graph-memory-group", "B1"]
    return run_experiment(systems, [LONG_KNOBS], [0, 1], stand_in, probe_days=(3,))


def test_a_long_game_runs_to_the_horizon_on_every_system(long_rows):
    assert {r["system"] for r in long_rows} == {"graph-memory", "graph-memory-group", "B1"}
    assert all(r["days"] == 12 for r in long_rows)
    assert all(isinstance(r["ignitions"], int) and r["ignitions"] > 0 for r in long_rows)


def test_saboteurs_lie_in_a_long_game(long_rows):
    assert all(isinstance(r["false_messages"], int) and r["false_messages"] > 0 for r in long_rows)


def test_the_role_card_warns_that_wasted_water_counts():
    card = ringfire.role_card("A1", 8, (1,), cooldown=3, waste_penalty=0.5)
    assert "wait 3 days" in card and "counts as 0.5 of a burnt field" in card
    assert "counts as" not in ringfire.role_card("A1", 8, (1,), cooldown=3)


def test_loss_counts_honest_fields_plus_the_penalty_for_each_wasted_watering():
    knobs = Knobs(n_agents=8, imposters=1, horizon=8, regrow_days=2, waste_penalty=0.5)
    (row,) = run_experiment(
        ["graph-memory"], [knobs], [0], lambda s, k: honest_agent(k.n_agents), probe_days=()
    )
    honest, wasted = row["honest_ignitions"], row["water_wasted"]
    assert isinstance(honest, int) and isinstance(wasted, int)
    assert isinstance(row["ignitions"], int) and honest < row["ignitions"]  # the imposter's burnt
    assert row["loss"] == honest + 0.5 * wasted


# ---- the graph agent's context: map and what is worth telling ----------------------------------


def started_graph(game: Game) -> GraphBackend:
    backend = GraphBackend(MemoryStore())
    backend.start(game)
    return backend


def test_a_graph_agent_is_shown_the_same_map_as_a_log_agent():
    game = ring_game()
    graph, log = started_graph(game), SharedLogBackend()
    log.start(ring_game())
    assert graph.map_lines == log.map_lines
    assert "## Map\nF0 -> F1: fire takes 1 day(s) (A0 owns F0)" in graph.context(3, 1, 4000)


def test_a_fire_you_saw_is_worth_telling_each_neighbour_until_you_send_it():
    game = ring_game()
    backend = started_graph(game)
    hints = backend.worth_telling(0, 1)  # A0 saw its own field F0 catch fire on day 0
    assert [h.split(":")[0] for h in hints] == [
        '- send(to="A1", belief_id="B1")',
        '- send(to="A5", belief_id="B1")',
    ]
    belief = backend.store.belief("A0", "B1")
    assert belief is not None
    backend._send(lambda *a: "sent", "A0", "A1", belief)
    assert [h.split(":")[0] for h in backend.worth_telling(0, 1)] == [
        '- send(to="A5", belief_id="B1")'
    ]
    assert "## Worth doing" in backend.context(0, 1, 4000)


def test_nothing_is_worth_telling_the_agent_that_told_you_or_once_it_is_old():
    game = ring_game()
    backend = started_graph(game)
    message = game.send(0, 1, Claim(0, 0))
    assert message is not None
    backend.message(message)
    assert all('to="A0"' not in h for h in backend.worth_telling(1, 1))  # A0 told A1
    assert backend.worth_telling(0, 5) == []  # day 0 is long past by day 5


# ---- the fire outlook every system shows ---------------------------------------------------------


def test_the_outlook_forecasts_from_fires_seen_along_known_paths():
    edges = [(i, i + 1, 1) for i in range(6)]
    text = outlook(edges, [(2, 3)], [4, 5], today=4, window=None)
    assert "F4: fire due on day 5 unless stopped on the way (F2 seen burning on day 3)" in text
    assert "F5: fire due on day 6" in text


def test_a_fire_that_has_passed_says_nothing_and_a_later_one_is_used():
    edges = [(i, i + 1, 1) for i in range(6)]
    assert "F4: no fire you have seen" in outlook(edges, [(2, 0)], [4], today=5, window=None)
    assert "F4: fire due on day 11" in outlook(edges, [(2, 0), (3, 10)], [4], today=5, window=None)
    assert "F4: no fire you have seen" in outlook(
        edges, [(4, 6)], [4], today=5, window=None
    )  # its own fire


def test_a_field_that_burned_is_not_forecast_to_burn_again():
    ring = [(i, (i + 1) % 8, 1) for i in range(8)]  # the case a live game got wrong: F1 burned
    text = outlook(ring, [(0, 0), (1, 1), (4, 4)], [1], today=4, window=None)  # on day 1, and
    assert "F1: burned on day 1; it cannot burn again" in text  # F4's fire would come round
    assert "day 9" not in text


def test_fire_does_not_run_on_through_a_field_that_already_burned():
    line = [(0, 1, 1), (1, 2, 1), (2, 3, 1)]
    assert "F2: no fire you have seen" in outlook(line, [(1, 1), (0, 3)], [2], today=3, window=None)


def test_a_field_that_has_grown_back_can_burn_again():
    line = [(0, 1, 1), (1, 2, 1), (2, 3, 1)]
    text = outlook(line, [(1, 1), (0, 3)], [2], today=3, window=1)
    assert "F2: fire due on day 5" in text  # F1 grew back by day 4, so F0's fire passes it
    assert "F1: burned on day 1; it cannot burn again before day 3" in outlook(
        line, [(1, 1)], [1], today=2, window=1
    )


def test_graph_and_log_agents_get_the_same_outlook():
    game = ring_game()
    graph, log = started_graph(game), SharedLogBackend()
    log.start(game)
    for _ in range(2):
        result = game.step()
        graph.day(game, result)
        log.day(game, result)
    section = "## Fire outlook"
    graph_outlook = graph.context(0, 2, 4000).split(section)[1].split("\n\n")[0]
    log_outlook = log.context(0, 2, 4000).split(section)[1].split("\n\n")[0]
    assert graph_outlook == log_outlook


# ---- group correction ---------------------------------------------------------------------------


def warned_game(quorum=1):
    """Ring of 8, saboteur A4. On day 1 it tells A3 that F3 burns on day 2 (really day 3)."""
    game = ring_game(n=8, horizon=14, imposters=(Imposter(4, Behaviour.SABOTEUR),))
    pipeline = Pipeline(MemoryStore(), warn_quorum=quorum)
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    pipeline.day(game, game.step())
    lie = game.send(4, 3, Claim(3, 2))
    assert lie is not None
    pipeline.message(lie)
    return game, pipeline


def play_days(game: Game, pipeline: Pipeline, n: int) -> None:
    for _ in range(n):
        pipeline.day(game, game.step())


def distrusting(pipeline: Pipeline, agent: str) -> list[str]:
    return sorted(v for v, a in pipeline.exposed if a == agent)


def test_a_liar_caught_first_hand_is_warned_about_one_hop_a_day():
    game, pipeline = warned_game()
    play_days(game, pipeline, 1)  # day 1 played: nothing expired yet
    assert distrusting(pipeline, "A4") == []
    play_days(game, pipeline, 1)  # day 2 played: no fire at F3, A3 catches A4 and warns A2
    assert distrusting(pipeline, "A4") == ["A3"]
    play_days(game, pipeline, 1)  # A2 hears it, distrusts A4, and warns A1
    assert distrusting(pipeline, "A4") == ["A2", "A3"]
    play_days(game, pipeline, 2)
    assert distrusting(pipeline, "A4") == ["A0", "A1", "A2", "A3"]
    reasons = {e.viewer: e.reason for e in pipeline.exposures}
    assert reasons["A2"] == "warned by A3"
    assert "A4" not in {w.receiver for w in pipeline.warnings}  # the liar is never told


def test_the_warning_goes_round_the_ring_until_it_meets_the_liar():
    game, pipeline = warned_game()
    play_days(game, pipeline, 12)
    assert distrusting(pipeline, "A4") == ["A0", "A1", "A2", "A3", "A5", "A6", "A7"]


def test_an_honest_agent_who_relayed_a_lie_is_not_warned_about():
    game = ring_game(n=8, horizon=14, imposters=(Imposter(4, Behaviour.SABOTEUR),))
    pipeline = Pipeline(MemoryStore(), warn_quorum=1)
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    pipeline.day(game, game.step())
    lie = game.send(4, 5, Claim(6, 2))  # F6 really burns on day 6
    assert lie is not None
    pipeline.message(lie)
    relayed = game.send(5, 6, lie.claim, lie)  # honest A5 passes it on in good faith
    assert relayed is not None
    pipeline.message(relayed)
    play_days(game, pipeline, 6)
    assert "A6" in distrusting(pipeline, "A5")  # A6 blames who told it...
    assert all(w.accused != "A5" for w in pipeline.warnings)  # ...but does not spread that


def test_a_warning_from_someone_you_distrust_is_ignored():
    game, pipeline = warned_game()
    pipeline.caught.add(("A2", "A3"))  # A2 has caught A3 lying; A3 is the only reporter
    play_days(game, pipeline, 4)
    assert "A2" not in distrusting(pipeline, "A4")


def test_with_a_quorum_of_two_one_reporter_is_not_enough():
    game, pipeline = warned_game(quorum=2)
    play_days(game, pipeline, 6)
    assert distrusting(pipeline, "A4") == ["A3"]


def test_without_a_quorum_nobody_warns_anybody():
    game, pipeline = warned_game(quorum=None)
    play_days(game, pipeline, 6)
    assert pipeline.warnings == [] and distrusting(pipeline, "A4") == ["A3"]


def test_an_agent_sees_its_known_liars_and_how_to_route_around_them():
    game = ring_game(n=8, horizon=14, imposters=(Imposter(4, Behaviour.SABOTEUR),))
    backend = GraphBackend(MemoryStore(), warn_quorum=1)
    backend.start(game)
    backend.day(game, game.step())
    lie = game.send(4, 3, Claim(3, 2))
    assert lie is not None
    backend.message(lie)
    for _ in range(2):
        backend.day(game, game.step())
    context = backend.context(3, 3, 4000)
    assert "## Known liars" in context and "- A4: told F3 on day 2" in context
    assert 'act(type="link", target="A5"): route around A4' in context


def test_group_correction_spreads_who_the_liars_are(long_rows):
    def coverage(system: str) -> float:
        values = [r["liar_coverage"] for r in long_rows if r["system"] == system]
        return sum(v for v in values if isinstance(v, float))

    assert coverage("graph-memory-group") > coverage("graph-memory")
    group = [r for r in long_rows if r["system"] == "graph-memory-group"]
    assert all(isinstance(r["warnings"], int) and r["warnings"] > 0 for r in group)
    plain = {r["seed"]: r for r in long_rows if r["system"] == "graph-memory"}
    for row in group:  # a warning is only ever about a first-hand liar: no new honest victims
        assert row["honest_distrusted"] == plain[row["seed"]]["honest_distrusted"]


def test_telling_a_neighbour_about_a_start_fire_does_not_get_you_blamed():
    """A start fire is published before anyone speaks. A neighbour told about it on day 0 must be
    shown it, not left to conclude that no fire came and blame the honest sender."""
    game = ring_game(rules=FireRules())
    pipeline = Pipeline(MemoryStore())
    pipeline.start(game)
    pipeline.publish_start_fires(game)
    news = game.send(0, 1, Claim(0, 0))  # A0 owns F0, which is burning: true
    assert news is not None
    pipeline.message(news)
    pipeline.day(game, game.step())
    assert pipeline.exposures == []
    assert (1, 0, 0) in pipeline.shown
