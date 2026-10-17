"""The Hualien quake as a world for a team on the frame: the reports that arrive, the fabs, and the
truth to score the team against.

The figures are the real ones (adapter.py): the tsunami warning centres' early solution, magnitude
7.5 at 11 km (PTWC and ATWC), and USGS's reviewed solution, magnitude 7.4 at 40 km (USGS event
us7000m9g4). The rest is made up to make a case: the timing is compressed to a few ticks, the
three fabs are invented, and so is a rumour account that claims a bigger quake and a flooded fab.

  tick 0   PTWC and ATWC: magnitude 7.5, depth 11 km
  tick 1   the rumour account: magnitude 8.1, "FabA is flooded" (the fab's own sensors say it is
           running)
  tick 3   USGS's reviewed solution: magnitude 7.4, depth 40 km

What the team should leave behind: each fab's alert at the level the reviewed figures give (FabA
falls from high to medium, FabB stays low, FabC stays high), nothing resting on the rumour, the
rumour account distrusted, and the warning centres trusted (an early figure that is later revised
is not a lie).
"""

from dataclasses import dataclass, field
from typing import Any

from .adapter import DEPTH, MAGNITUDE

QUAKE = "us7000m9g4"
RUMOUR = "@quake_alerts_now"  # invented
FAB_STATUS = "fab.status"
# fab -> km from the epicentre (invented)
FABS = {"FabA": 120, "FabB": 300, "FabC": 60}


@dataclass
class Report:
    id: str
    tick: int
    source: str
    text: str
    claims: list[tuple[str, str, Any]]
    about: list[str]
    rumour: bool = False


REPORTS = [
    Report(
        "r1",
        0,
        "PTWC",
        "Tsunami information statement: an earthquake of magnitude 7.5 occurred near the east "
        "coast of Taiwan at a depth of 11 km.",
        [(QUAKE, MAGNITUDE, 7.5), (QUAKE, DEPTH, 11.0)],
        [QUAKE],
    ),
    Report(
        "r2",
        0,
        "ATWC",
        "Preliminary magnitude 7.5, depth 11 km, near the east coast of Taiwan.",
        [(QUAKE, MAGNITUDE, 7.5), (QUAKE, DEPTH, 11.0)],
        [QUAKE],
    ),
    Report(
        "r3",
        1,
        RUMOUR,
        "BREAKING: it was a magnitude 8.1! FabA is flooded, the whole site is under water. "
        "Evacuate everything now!!",
        [(QUAKE, MAGNITUDE, 8.1), ("FabA", FAB_STATUS, "flooded")],
        [QUAKE, "FabA"],
        rumour=True,
    ),
    Report(
        "r4",
        3,
        "USGS",
        "Reviewed solution for us7000m9g4: magnitude 7.4, depth 40 km.",
        [(QUAKE, MAGNITUDE, 7.4), (QUAKE, DEPTH, 40.0)],
        [QUAKE],
    ),
]


def exposure(magnitude: float, depth_km: float, distance_km: float) -> str:
    """The adapter's rule of thumb (adapter.assess_exposure): strength falls with distance and
    rises when the quake is shallow."""
    effective = round(magnitude - distance_km / 100 + max(0, 30 - depth_km) / 100, 2)
    return "high" if effective >= 6.4 else "medium" if effective >= 5.5 else "low"


@dataclass
class Alert:
    id: str
    tick: int
    fab: str
    level: str
    withdrawn: bool = False


@dataclass
class QuakeWorld:
    """The reports' script and the fabs' state. `tick` advances with the runtime."""

    tick: int = 0
    delivered: list[Report] = field(default_factory=list[Report])
    alerts: list[Alert] = field(default_factory=list[Alert])

    def reports_due(self, tick: int) -> list[Report]:
        found = [r for r in REPORTS if r.tick == tick]
        self.delivered.extend(found)
        return found

    def fab_status(self, fab: str) -> str:
        if fab not in FABS:
            raise ValueError(f"no fab {fab}; the fabs are {', '.join(FABS)}")
        return "running"  # no fab was damaged in this made-up case

    def alert(self, fab: str, level: str) -> Alert:
        if fab not in FABS:
            raise ValueError(f"no fab {fab}; the fabs are {', '.join(FABS)}")
        if level not in ("high", "medium", "low"):
            raise ValueError("level is high, medium or low")
        for old in self.alerts:
            if old.fab == fab and not old.withdrawn:
                old.withdrawn = True  # a fab has one alert in force: the new one replaces it
        made = Alert(f"A{len(self.alerts) + 1}", self.tick, fab, level)
        self.alerts.append(made)
        return made

    def in_force(self) -> dict[str, str]:
        return {a.fab: a.level for a in self.alerts if not a.withdrawn}

    def checks(self) -> dict[str, bool]:
        """The alerts in force at the end, against what the reviewed figures give."""
        now = self.in_force()
        found: dict[str, bool] = {}
        for fab, distance in FABS.items():
            early = exposure(7.5, 11, distance)
            right = exposure(7.4, 40, distance)
            if right == "low":
                found[f"{fab}: no alert above low"] = now.get(fab, "low") == "low"
            elif early != right:
                found[f"{fab}: the alert is {right} (the reviewed figures), not {early}"] = (
                    now.get(fab) == right
                )
            else:
                found[f"{fab}: the alert is {right}"] = now.get(fab) == right
        return found
