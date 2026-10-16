import pytest

from graph_agent.sim.comms import Behaviour, Claim, Imposter, LinkError, Network

CLAIM = Claim(field_id=5, day=4)


def net(*imposters, n=6) -> Network:
    return Network(n, imposters)


def test_agents_start_linked_to_both_ring_neighbours():
    network = net()
    assert network.neighbours(0) == [1, 5]
    assert network.neighbours(3) == [2, 4]
    assert not network.linked(0, 3)


def test_a_message_over_a_missing_link_is_rejected_until_a_shortcut_is_added():
    network = net()
    with pytest.raises(LinkError):
        network.send(0, 3, CLAIM, day=0)
    network.add_link(0, 3)
    assert network.send(0, 3, CLAIM, day=0).receiver == 3


def test_route_is_recorded_by_the_engine_as_the_claim_is_passed_on():
    network = net()
    a = network.send(0, 1, CLAIM, day=0)
    b = network.send(1, 2, CLAIM, day=1, relaying=a)
    c = network.send(2, 3, CLAIM, day=2, relaying=b)
    assert (a.route, b.route, c.route) == ((0,), (0, 1), (0, 1, 2))
    assert c.origin == 0


def test_a_message_is_received_at_once_and_can_be_relayed_the_same_day():
    network = net()
    a = network.send(0, 1, CLAIM, day=0)
    assert network.messages_to(1, day=0) == [a]
    b = network.send(1, 2, CLAIM, day=0, relaying=a)
    assert b.route == (0, 1) and network.messages_to(2, day=0) == [b]
    assert network.messages_to(2, day=1) == []


def test_an_agent_cannot_relay_a_message_it_has_not_received():
    network = net()
    a = network.send(0, 1, CLAIM, day=0)
    with pytest.raises(LinkError):
        network.send(3, 4, CLAIM, day=0, relaying=a)  # agent 3 never received it


def test_hide_fire_swallows_messages_and_keeps_a_record():
    network = net(Imposter(1, Behaviour.HIDE_FIRE))
    a = network.send(0, 1, CLAIM, day=0)
    assert network.send(1, 2, CLAIM, day=1, relaying=a) is None
    assert network.messages_to(2, day=1) == [] and len(network.dropped) == 1


def test_subtle_bias_moves_the_day_by_one_and_is_marked():
    network = net(Imposter(1, Behaviour.SUBTLE_BIAS))
    a = network.send(0, 1, CLAIM, day=0)
    b = network.send(1, 2, CLAIM, day=1, relaying=a)
    assert b.claim == Claim(5, 5) and b.altered_by == (1,)
    assert b.route == (0, 1)  # imposters cannot change the route


def test_an_honest_relay_of_an_altered_claim_stays_marked():
    network = net(Imposter(1, Behaviour.SUBTLE_BIAS))
    a = network.send(0, 1, CLAIM, day=0)
    b = network.send(1, 2, CLAIM, day=1, relaying=a)
    c = network.send(2, 3, b.claim, day=2, relaying=b)
    assert c.altered_by == (1,) and c.route == (0, 1, 2)


def test_false_alarm_marks_what_it_originates_but_not_what_it_relays():
    network = net(Imposter(1, Behaviour.FALSE_ALARM))
    own = network.send(1, 2, Claim(3, 9), day=0)
    a = network.send(0, 1, CLAIM, day=0)
    passed_on = network.send(1, 2, CLAIM, day=1, relaying=a)
    assert own.altered_by == (1,) and passed_on.altered_by == ()
