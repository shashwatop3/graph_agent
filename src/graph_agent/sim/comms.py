"""Messages between agents. Delivery is instant, and the engine records the true route of each one.

An agent (or a script) says who to send what to. The network checks the link exists, works out the
route and applies the sender's imposter behaviour if it has one. Imposters can change what a
message says, but never the route.
"""

from dataclasses import dataclass, replace
from enum import Enum


class LinkError(ValueError):
    """A message was sent over a link that does not exist, or relayed without being received."""


@dataclass(frozen=True)
class Claim:
    """ "Fire reaches `field_id` on `day`." The only thing messages say in v1."""

    field_id: int
    day: int


@dataclass(frozen=True)
class Message:
    id: int
    origin: int  # the agent that first sent this claim
    sender: int
    receiver: int
    day: int  # sent and received on the same day
    claim: Claim
    route: tuple[int, ...]  # every agent the claim passed through, ending with the sender
    altered_by: tuple[int, ...] = ()  # imposters that originated or changed the claim on the way


class Behaviour(Enum):
    FALSE_ALARM = "false_alarm"  # everything it originates is a scripted lie; relays are honest
    HIDE_FIRE = "hide_fire"  # sends and relays nothing
    SUBTLE_BIAS = "subtle_bias"  # the day in every claim it sends is one day later
    # wants fields to burn: everything it originates is a lie timed to waste a watering (see
    # saboteur.py), and every claim it relays says one day earlier, so the receiver waters too
    # soon and is still resting when the fire really comes
    SABOTEUR = "saboteur"


@dataclass(frozen=True)
class Imposter:
    agent: int
    behaviour: Behaviour


class Network:
    def __init__(self, n_agents: int, imposters: tuple[Imposter, ...] = ()):
        self.n_agents = n_agents
        self.imposters = {i.agent: i.behaviour for i in imposters}
        # Initially each agent is linked to both ring neighbours.
        self.links = {frozenset((a, (a + 1) % n_agents)) for a in range(n_agents)}
        self.log: list[Message] = []  # every message that was sent, in order
        self.dropped: list[Message] = []  # messages a HIDE_FIRE imposter swallowed
        self._next_id = 0

    def add_link(self, a: int, b: int) -> None:
        """A shortcut edge between two agents (agents build these to skip an imposter)."""
        self.links.add(frozenset((a, b)))

    def linked(self, a: int, b: int) -> bool:
        return frozenset((a, b)) in self.links

    def neighbours(self, agent: int) -> list[int]:
        return sorted(next(iter(link - {agent})) for link in self.links if agent in link)

    def messages_to(self, agent: int, day: int) -> list[Message]:
        """What `agent` received on `day`."""
        return [m for m in self.log if m.receiver == agent and m.day == day]

    def send(
        self,
        sender: int,
        receiver: int,
        claim: Claim,
        day: int,
        relaying: Message | None = None,
    ) -> Message | None:
        """Send `claim`. Pass the message being passed on as `relaying`, or None for a first report.

        Returns the message, or None if a HIDE_FIRE imposter swallowed it.
        """
        if not self.linked(sender, receiver):
            raise LinkError(f"agents {sender} and {receiver} are not linked")
        if relaying is not None and relaying.receiver != sender:
            raise LinkError(f"agent {sender} never received message {relaying.id}")

        message = Message(
            id=self._next_id,
            origin=sender if relaying is None else relaying.origin,
            sender=sender,
            receiver=receiver,
            day=day,
            claim=claim,
            route=(sender,) if relaying is None else (*relaying.route, sender),
            altered_by=() if relaying is None else relaying.altered_by,
        )
        self._next_id += 1

        message = self._apply_behaviour(message, originating=relaying is None)
        if message is not None:
            self.log.append(message)
        return message

    def _apply_behaviour(self, message: Message, originating: bool) -> Message | None:
        behaviour = self.imposters.get(message.sender)
        if behaviour is Behaviour.HIDE_FIRE:
            self.dropped.append(message)
            return None
        if behaviour is Behaviour.SUBTLE_BIAS:
            claim = Claim(message.claim.field_id, message.claim.day + 1)
            return replace(message, claim=claim, altered_by=(*message.altered_by, message.sender))
        if behaviour is Behaviour.SABOTEUR and not originating:
            claim = Claim(message.claim.field_id, message.claim.day - 1)
            return replace(message, claim=claim, altered_by=(*message.altered_by, message.sender))
        if behaviour in (Behaviour.FALSE_ALARM, Behaviour.SABOTEUR) and originating:
            return replace(message, altered_by=(*message.altered_by, message.sender))
        return message
