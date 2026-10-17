"""The event log: everything that happens in a run, in order, for nodes to wake on and to watch.

Every change in a run is appended here as one `Event`: a tick began, an item arrived, a message was
delivered, a node took a turn, a belief changed, someone was exposed, an action was proposed or
approved. Nodes wake on events (see spec.Trigger); the console streams them live.

The kinds the frame emits: run_start, tick, item, message, turn, tool, change, exposure, warning,
proposal, decision, action, held, tick_end, run_end. A pack may add its own (extract, world); the
console shows unknown kinds as plain rows.
"""

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Event:
    seq: int
    tick: int
    kind: str
    data: dict[str, Any] = field(default_factory=dict[str, Any])


Listener = Callable[[Event], None]


class EventLog:
    """Append-only, numbered from 1. Listeners are called for every new event, in order."""

    def __init__(self) -> None:
        self.events: list[Event] = []
        self._listeners: list[Listener] = []
        self._lock = threading.Lock()

    def emit(self, tick: int, kind: str, **data: Any) -> Event:
        with self._lock:
            event = Event(len(self.events) + 1, tick, kind, data)
            self.events.append(event)
            listeners = list(self._listeners)
        for listener in listeners:
            listener(event)
        return event

    def since(self, seq: int) -> list[Event]:
        """Every event after `seq` (0 for all)."""
        with self._lock:
            return self.events[seq:]

    def listen(self, listener: Listener) -> Callable[[], None]:
        """Call `listener` for every new event. Returns a function that stops it."""
        with self._lock:
            self._listeners.append(listener)

        def stop() -> None:
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return stop
