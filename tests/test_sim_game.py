from graph_agent.sim.comms import Behaviour, Claim, Imposter
from graph_agent.sim.game import Game
from graph_agent.sim.oracle import Oracle
from graph_agent.sim.world import Edge, World, WorldConfig


def ring_world(n=6, fires=((0, 1.0),)) -> World:
    config = WorldConfig(n_agents=n, fields_per_agent=1, n_hidden_edges=0)
    edges = tuple(Edge(i, (i + 1) % n, 1) for i in range(n))
    return World(config=config, seed=0, edges=edges, initial_fires=tuple(fires))


def play_out(game: Game):
    results = []
    while not game.finished:
        results.append(game.step())
    return results


# ---- game -------------------------------------------------------------------------------------


def test_evidence_is_published_when_fire_reaches_a_field_including_the_start_fires():
    results = play_out(Game(ring_world()))
    evidence = [(e.day, e.field_id, e.owner) for r in results for e in r.evidence]
    assert evidence == [(d, d, d) for d in range(6)]  # fire reaches field d on day d


def test_messages_are_received_the_day_they_are_sent():
    game = Game(ring_world())
    message = game.send(0, 1, Claim(3, 3))
    assert game.net.messages_to(1, game.day) == [message]
    game.step()
    assert game.net.messages_to(1, game.day) == []


def test_the_game_is_finished_when_the_fire_is_out():
    game = Game(ring_world(n=3))
    assert not game.finished
    play_out(game)
    assert game.finished


# ---- oracle -----------------------------------------------------------------------------------


def chain_with_bias():
    """0 -> 1 -> 2 -> 3, agent 2 shifts the day by one. Fire reaches field f on day f."""
    game = Game(ring_world(), imposters=(Imposter(2, Behaviour.SUBTLE_BIAS),))
    true = Claim(3, 3)
    a = game.send(0, 1, true)
    game.step()
    b = game.send(1, 2, true, relaying=a)
    game.step()
    c = game.send(2, 3, true, relaying=b)
    play_out(game)
    return game, (a, b, c)


def test_oracle_knows_what_is_true_only_from_the_engine():
    game, _ = chain_with_bias()
    oracle = Oracle(game)
    assert oracle.claim_is_true(Claim(3, 3)) is True
    assert oracle.claim_is_true(Claim(3, 4)) is False
    assert oracle.claim_is_true(Claim(5, 99)) is False


def test_oracle_marks_a_wrong_claim_even_from_an_honest_agent():
    game = Game(ring_world())
    game.send(0, 1, Claim(4, 2))  # honest sender, wrong claim; the oracle does not care who
    play_out(game)
    oracle = Oracle(game)
    assert len(oracle.false_messages()) == 1
    assert oracle.tainted_messages() == []
    assert oracle.imposters == frozenset()


def test_oracle_separates_tainted_messages_from_clean_ones():
    game, (a, b, c) = chain_with_bias()
    oracle = Oracle(game)
    assert oracle.imposters == {2} and oracle.is_imposter(2)
    assert oracle.tainted_messages() == [c]
    assert oracle.false_messages() == [c]


def test_exposing_an_agent_removes_support_from_exactly_the_messages_routed_through_it():
    game, (a, b, c) = chain_with_bias()
    oracle = Oracle(game)
    assert oracle.lost_if_exposed(2) == [c]
    assert oracle.lost_if_exposed(1) == [b, c]
    assert oracle.lost_if_exposed(5) == []
    assert oracle.depends_on(c) == {0, 1, 2}


def test_claims_about_the_future_are_undecided():
    game = Game(ring_world())
    game.step()
    assert Oracle(game).claim_is_true(Claim(5, 5)) is None


def test_collusion_is_several_false_alarms_with_the_same_claim():
    imposters = tuple(Imposter(a, Behaviour.FALSE_ALARM) for a in (1, 2, 3))
    game = Game(ring_world(), imposters=imposters)
    lie = Claim(5, 1)  # fire does not reach field 5 until day 5
    game.net.add_link(1, 4)
    game.net.add_link(2, 4)
    game.net.add_link(3, 4)
    for liar in (1, 2, 3):
        game.send(liar, 4, lie)
    play_out(game)
    oracle = Oracle(game)
    assert {m.sender for m in oracle.false_messages()} == {1, 2, 3}
    assert len(oracle.tainted_messages()) == 3  # counting confirmations would have said "3 sources"
