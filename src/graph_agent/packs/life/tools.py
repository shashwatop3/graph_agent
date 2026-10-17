"""The simulated services as tools, shaped like MCP tools (and served over MCP by mcp_server.py).

Reading tools are free to call. Checking tools (flight_status, booking_check, account_status,
subscriptions_list) also return what they establish as claims, which the frame records as evidence
for the caller, so the checker can test what mails said against it. Outward tools (calendar
writes, cabs, sending mail, tasks, subscription changes, payments) change the world, so each one
names the beliefs it rests on and may wait for a person's approval.

Names use underscores: model providers reject dots in tool names.
"""

import json
from typing import Any

from graph_agent.frame.tools import ToolSpec, schema_of
from graph_agent.harness.llm import Json

from .world import DAYS, Cab, Event, LifeWorld, Payment, Sent, Task, minutes

STRING: dict[str, Json] = {"type": "string"}
NUMBER: dict[str, Json] = {"type": "number"}
BOOLEAN: dict[str, Json] = {"type": "boolean"}


def _when(value: Any) -> str:
    """Check a time such as "Fri 04:30" and return it in that form."""
    text = str(value).strip()
    try:
        total = minutes(text)
    except (ValueError, IndexError) as error:
        raise ValueError(
            f"times look like 'Fri 04:30' (day {'/'.join(DAYS)}), not {text!r}"
        ) from error
    return f"{DAYS[total // 1440]} {total % 1440 // 60:02d}:{total % 60:02d}"


def _dump(value: object) -> str:
    return json.dumps(value, default=lambda o: o.__dict__)


class LifeTools:
    """Every service's tools over one LifeWorld."""

    def __init__(self, world: LifeWorld):
        self.world = world

    def list_tools(self) -> list[ToolSpec]:
        w = self.world
        return [
            # ---- mail ----
            ToolSpec(
                "mail_search",
                "List mails (received and sent) whose sender, subject or text contains `query`.",
                schema_of({"query": STRING}, ["query"]),
                self._mail_search,
            ),
            ToolSpec(
                "mail_read",
                "Read one mail in full by its id (such as m4).",
                schema_of({"id": STRING}, ["id"]),
                self._mail_read,
            ),
            ToolSpec(
                "mail_send",
                "Send a mail on the person's behalf.",
                schema_of(
                    {"to": STRING, "subject": STRING, "body": STRING}, ["to", "subject", "body"]
                ),
                self._mail_send,
                outward=True,
            ),
            # ---- calendar ----
            ToolSpec(
                "calendar_list",
                "List the calendar's events (id, title, start, end).",
                schema_of({}),
                lambda a: _dump([e for e in w.events.values() if not e.deleted]),
            ),
            ToolSpec(
                "calendar_create",
                "Create a calendar event. Times look like 'Fri 04:30'.",
                schema_of(
                    {"title": STRING, "start": STRING, "end": STRING}, ["title", "start", "end"]
                ),
                self._calendar_create,
                outward=True,
            ),
            ToolSpec(
                "calendar_move",
                "Move a calendar event to a new start and end.",
                schema_of(
                    {"event_id": STRING, "start": STRING, "end": STRING},
                    ["event_id", "start", "end"],
                ),
                self._calendar_move,
                outward=True,
            ),
            ToolSpec(
                "calendar_delete",
                "Delete a calendar event.",
                schema_of({"event_id": STRING}, ["event_id"]),
                self._calendar_delete,
                outward=True,
            ),
            # ---- travel ----
            ToolSpec(
                "flight_status",
                "The airline's live status for a flight: when it departs now.",
                schema_of({"flight": STRING}, ["flight"]),
                self._flight_status,
                observes=lambda a, r: [
                    (str(a["flight"]).upper(), "flight.departs", json.loads(r)["departs"])
                ],
            ),
            ToolSpec(
                "booking_check",
                "The airline's own record of a booking (such as ABC123): its flight, and any "
                "payment due.",
                schema_of({"ref": STRING}, ["ref"]),
                lambda a: _dump(w.booking(str(a["ref"]))),
                observes=lambda a, r: [
                    (
                        f"booking-{json.loads(r)['booking']}",
                        "booking.payment_due",
                        json.loads(r)["payment_due"],
                    )
                ],
            ),
            ToolSpec(
                "cab_book",
                "Book a cab. `pickup` looks like 'Fri 04:30'.",
                schema_of({"pickup": STRING, "to": STRING}, ["pickup", "to"]),
                self._cab_book,
                outward=True,
            ),
            ToolSpec(
                "cab_cancel",
                "Cancel a cab booking by its id.",
                schema_of({"cab_id": STRING}, ["cab_id"]),
                self._cab_cancel,
                outward=True,
            ),
            ToolSpec(
                "cab_list",
                "List cab bookings.",
                schema_of({}),
                lambda a: _dump([c for c in w.cabs.values() if not c.cancelled]),
            ),
            # ---- tasks ----
            ToolSpec(
                "tasks_list",
                "List the person's tasks.",
                schema_of({}),
                lambda a: _dump(list(w.tasks.values())),
            ),
            ToolSpec(
                "tasks_create",
                "Create a task with a due time such as 'Thu 17:00'.",
                schema_of({"title": STRING, "due": STRING}, ["title", "due"]),
                self._tasks_create,
                outward=True,
            ),
            ToolSpec(
                "tasks_update",
                "Change a task's due time, or mark it done.",
                schema_of({"task_id": STRING, "due": STRING, "done": BOOLEAN}, ["task_id"]),
                self._tasks_update,
                outward=True,
            ),
            # ---- money ----
            ToolSpec(
                "account_status",
                "The bank's own status for the main account.",
                schema_of({}),
                lambda a: _dump({"account": "acct-main", "status": w.account_status()}),
                observes=lambda a, r: [("acct-main", "account.status", json.loads(r)["status"])],
            ),
            ToolSpec(
                "subscriptions_list",
                "The bank's record of each subscription and the card it is charged to.",
                schema_of({}),
                lambda a: _dump(w.sub_cards),
                observes=lambda a, r: [
                    (sub, "subscription.card", card) for sub, card in json.loads(r).items()
                ],
            ),
            ToolSpec(
                "subscription_set_card",
                "Charge a subscription to a different card.",
                schema_of({"subscription": STRING, "card": STRING}, ["subscription", "card"]),
                self._set_card,
                outward=True,
            ),
            ToolSpec(
                "bank_pay",
                "Pay someone from the main account.",
                schema_of(
                    {"payee": STRING, "amount": NUMBER, "reference": STRING},
                    ["payee", "amount", "reference"],
                ),
                self._pay,
                outward=True,
            ),
        ]

    # ---- handlers -------------------------------------------------------------------------------

    def _mail_search(self, a: dict[str, Any]) -> str:
        query = str(a["query"]).lower()
        found = [
            {"id": m.id, "from": m.sender, "to": m.to, "subject": m.subject, "tick": m.tick}
            for m in self.world.inbox
            if m.feed in ("mail", "sent")
            and (query in m.sender.lower() or query in m.subject.lower() or query in m.body.lower())
        ]
        found += [
            {"id": s.id, "from": "me", "to": s.to, "subject": s.subject, "tick": s.tick}
            for s in self.world.sent
            if query in s.to.lower() or query in s.subject.lower() or query in s.body.lower()
        ]
        return _dump(found[-10:])

    def _mail_read(self, a: dict[str, Any]) -> str:
        for m in self.world.inbox:
            if m.id == a["id"]:
                return _dump(
                    {"id": m.id, "from": m.sender, "to": m.to, "subject": m.subject, "body": m.body}
                )
        for s in self.world.sent:
            if s.id == a["id"]:
                return _dump(s)
        raise ValueError(f"no mail {a['id']}")

    def _mail_send(self, a: dict[str, Any]) -> str:
        sent = Sent(
            self.world.next_id("out"),
            self.world.tick,
            str(a["to"]),
            str(a["subject"]),
            str(a["body"]),
        )
        self.world.sent.append(sent)
        return f"sent {sent.id} to {sent.to}"

    def _calendar_create(self, a: dict[str, Any]) -> str:
        event = Event(
            self.world.next_id("ev-"), str(a["title"]), _when(a["start"]), _when(a["end"])
        )
        self.world.events[event.id] = event
        return f"created {event.id}: {event.title}, {event.start} to {event.end}"

    def _event(self, event_id: str) -> Event:
        event = self.world.events.get(event_id)
        if event is None or event.deleted:
            raise ValueError(f"no event {event_id}")
        return event

    def _calendar_move(self, a: dict[str, Any]) -> str:
        event = self._event(str(a["event_id"]))
        event.start, event.end = _when(a["start"]), _when(a["end"])
        return f"moved {event.id} to {event.start} to {event.end}"

    def _calendar_delete(self, a: dict[str, Any]) -> str:
        self._event(str(a["event_id"])).deleted = True
        return f"deleted {a['event_id']}"

    def _flight_status(self, a: dict[str, Any]) -> str:
        flight = str(a["flight"]).upper()
        if flight != "SK101":
            raise ValueError(f"no flight {flight}")
        return _dump({"flight": flight, "departs": self.world.departure(), "status": "scheduled"})

    def _cab_book(self, a: dict[str, Any]) -> str:
        cab = Cab(self.world.next_id("cab-"), _when(a["pickup"]), str(a["to"]))
        self.world.cabs[cab.id] = cab
        return f"booked {cab.id}: pickup {cab.pickup} to {cab.to}"

    def _cab_cancel(self, a: dict[str, Any]) -> str:
        cab = self.world.cabs.get(str(a["cab_id"]))
        if cab is None or cab.cancelled:
            raise ValueError(f"no live cab {a['cab_id']}")
        cab.cancelled = True
        return f"cancelled {cab.id}"

    def _tasks_create(self, a: dict[str, Any]) -> str:
        task = Task(self.world.next_id("task-"), str(a["title"]), _when(a["due"]))
        self.world.tasks[task.id] = task
        return f"created {task.id}: {task.title}, due {task.due}"

    def _tasks_update(self, a: dict[str, Any]) -> str:
        task = self.world.tasks.get(str(a["task_id"]))
        if task is None:
            raise ValueError(f"no task {a['task_id']}")
        if a.get("due"):
            task.due = _when(a["due"])
        if a.get("done") is not None:
            task.done = bool(a["done"])
        return f"updated {task.id}: due {task.due}, {'done' if task.done else 'open'}"

    def _set_card(self, a: dict[str, Any]) -> str:
        sub, card = str(a["subscription"]), str(a["card"])
        if sub not in self.world.sub_cards:
            raise ValueError(f"no subscription {sub}; they are {', '.join(self.world.sub_cards)}")
        if card not in ("card-4242", "card-5555"):
            raise ValueError(f"no card {card}; the cards are card-4242 and card-5555")
        self.world.sub_cards[sub] = card
        return f"{sub} is now charged to {card}"

    def _pay(self, a: dict[str, Any]) -> str:
        payment = Payment(self.world.tick, str(a["payee"]), float(a["amount"]), str(a["reference"]))
        self.world.payments.append(payment)
        return f"paid {payment.amount:.2f} to {payment.payee}"
