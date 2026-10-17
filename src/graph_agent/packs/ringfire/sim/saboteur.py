"""What a saboteur says: lies timed so that honest agents waste their water.

Saboteurs share one goal, to make as many fields burn as possible. They know the true map, hidden
paths included, and where fire is now, so they can work out when it will reach each field if
nobody waters. With a watering cooldown the most damaging lie is "fire reaches your field the day
before it really does": the owner waters a day early, is still resting the next day, and the
field burns. Each saboteur tells that to every honest neighbour, once per coming fire.
"""

import heapq

from .comms import Claim
from .field import FieldState
from .game import Game


def projected_arrivals(game: Game) -> dict[int, int]:
    """field -> the day fire would next reach it if nobody watered, from the fire as it is now.

    The fires already on their way (sim.upcoming) are the starting points; from each one, fire
    goes on along every edge, hidden ones too. Fields burning right now are skipped: they cannot
    catch fire again until they have burnt out and regrown.
    """
    sim = game.sim
    max_weight = max((e.weight for e in sim.world.edges), default=1)
    arrival: dict[int, int] = {}
    heap: list[tuple[int, int]] = []
    for day in range(sim.day, sim.day + max_weight + 1):
        for ignition in sim.upcoming(day):
            if ignition.field_id not in arrival or day < arrival[ignition.field_id]:
                arrival[ignition.field_id] = day
                heapq.heappush(heap, (day, ignition.field_id))
    out: dict[int, list[tuple[int, int]]] = {}
    for edge in sim.world.edges:
        out.setdefault(edge.src, []).append((edge.dst, edge.weight))
    while heap:
        day, field_id = heapq.heappop(heap)
        if day > arrival.get(field_id, day):
            continue
        for dst, weight in out.get(field_id, []):
            if sim.fields[dst].state is FieldState.BURNING:
                continue
            if day + weight < arrival.get(dst, day + weight + 1):
                arrival[dst] = day + weight
                heapq.heappush(heap, (day + weight, dst))
    return {f: d for f, d in arrival.items() if sim.fields[f].state is not FieldState.BURNING}


def planned_lies(
    game: Game, saboteur: int, already: set[tuple[int, int, int]], lead: tuple[int, int] = (2, 3)
) -> list[tuple[int, Claim]]:
    """The lies `saboteur` tells today: (receiver, claim) pairs.

    For each honest neighbour and each of its fields that fire will reach between `lead[0]` and
    `lead[1]` days from now, claim it arrives one day earlier. A claim sent today is read on a
    later turn, so the fake day must be at least tomorrow. `already` holds (receiver, field, true
    day) triples that have been lied about, and is updated, so no fire is lied about twice.
    """
    today = game.day
    projected = projected_arrivals(game)
    world = game.sim.world
    lies: list[tuple[int, Claim]] = []
    for neighbour in game.net.neighbours(saboteur):
        if neighbour in game.net.imposters:
            continue
        for field_id in world.fields_of(neighbour):
            true_day = projected.get(field_id)
            if true_day is None or not lead[0] <= true_day - today <= lead[1]:
                continue
            key = (neighbour, field_id, true_day)
            if key in already:
                continue
            already.add(key)
            lies.append((neighbour, Claim(field_id, true_day - 1)))
    return lies
