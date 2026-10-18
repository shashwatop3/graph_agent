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

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from .adapter import DEPTH, MAGNITUDE

QUAKE = "us7000m9g4"
RUMOUR = "@quake_alerts_now"  # invented
FAB_STATUS = "fab.status"
# fab -> km from the epicentre (invented)
FABS = {"FabA": 120, "FabB": 300, "FabC": 60}


TSUNAMI = "quake.tsunami"
PLACE = "quake.place"
GDACS_ALERT = "quake.gdacs_alert"
BULLETIN = "quake.bulletin"


@dataclass
class Report:
    id: str
    tick: int
    source: str
    text: str
    claims: list[tuple[str, str, Any]]
    about: list[str]
    rumour: bool = False
    feed: str = "reports"
    written: bool = False  # a post written for the replay, not a real one (see DAY)


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


# ---- the day: three real quakes, as the agencies reported them, and four posts ------------------
"""The "day" team's script: the first 50 minutes after the main shock, 00:10 to 00:55 UTC on
3 April 2024, a tick every 5 minutes. Three real quakes (USGS ids, origin times, positions,
magnitudes and depths as USGS, EMSC, GDACS and the warning centres recorded them, read on
2026-10-18 from their archives):

  us7000m9g4  23:58:12  M7.4 Mww, 40 km     the main shock, 15 km S of Hualien City
                         early: PTWC 7.5 Mi, 11.4 km (00:09:47); ATWC 7.5 Mi, 11 km (00:11:50)
                         EMSC 7.4 mw, 20 km; GDACS orange, 7.4, 34.75 km
  us7000m9gc  00:11:25  M6.4 Mww, 13.9 km   13 minutes later, 30 km to the north
  us7000m9gh  00:35:36  M5.6 mb, 15.9 km    (EMSC: 5.7 mb, 9.5 km)

When each report reached the desk is real for the warning centres and approximate for the rest:
the archives keep each agency's latest version, not when it was first published. The four posts
are written for the replay (Bluesky's archive needs an account to search) and say so: one
exaggerates and claims a flooded fab, one rightly passes on a tsunami warning, one rightly
reports the aftershock, one is a joke.

A report does not say which quake it is about: each agency has its own id, and a post names
none. The world matches it (`match`): a report is the same quake as one already known when their
origin times are within 2 minutes and they are within 60 km; a post is about the quake whose
magnitude it names, else the latest. Matching by region and date instead would make the main
shock and both aftershocks one quake.
"""


@dataclass
class Reading:
    """One agency's report of a quake, before it is matched to a quake."""

    id: str  # the agency's own id
    tick: int
    source: str
    feed: str
    origin: str  # ISO 8601, UTC
    lat: float
    lon: float
    magnitude: float
    depth_km: float
    text: str
    tsunami: bool | None = None
    place: str = ""
    gdacs_alert: str = ""


@dataclass
class Post:
    """A post (written for the replay): what it claims of the quake it is about."""

    id: str
    tick: int
    source: str
    text: str
    magnitude: float | None = None  # a magnitude it names: what matches it to a quake
    # (predicate, value): what it claims of that quake
    claims: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
    fab: tuple[str, str] | None = None  # a claim about a fab: (fab, status)
    rumour: bool = False


DAY: list[Reading | Post] = [
    Reading(
        "pt24093050",
        0,
        "PTWC",
        "centres",
        "2024-04-02T23:58:00Z",
        23.8,
        121.7,
        7.5,
        11.4,
        "PTWC tsunami threat message: magnitude 7.5 (Mi), depth 11 km, near the east coast "
        "of Taiwan. Hazardous waves are possible.",
        tsunami=True,
        place="east coast of Taiwan",
    ),
    Reading(
        "at00sbcakx",
        1,
        "ATWC",
        "centres",
        "2024-04-02T23:58:09Z",
        23.8,
        121.7,
        7.5,
        11.0,
        "ATWC: preliminary magnitude 7.5 (Mi), depth 11 km, Taiwan.",
        tsunami=True,
    ),
    Post(
        "p1",
        1,
        RUMOUR,
        "BREAKING: it was a magnitude 8.1! FabA is flooded, the whole site is "
        "under water. Evacuate everything now!!",
        8.1,
        [(MAGNITUDE, 8.1)],
        ("FabA", "flooded"),
        rumour=True,
    ),
    Reading(
        "us7000m9gc",
        2,
        "USGS",
        "usgs",
        "2024-04-03T00:11:25Z",
        24.1021,
        121.6812,
        6.4,
        13.9,
        "M 6.4 - 15 km NNE of Hualien City, Taiwan (us7000m9gc), depth 13.9 km.",
        tsunami=False,
        place="15 km NNE of Hualien City, Taiwan",
    ),
    Post(
        "p2",
        2,
        "@okinawa_local",
        "Tsunami warning just issued for Okinawa after the big 7.4 off Taiwan. Heading uphill.",
        7.4,
        [(TSUNAMI, "yes")],
    ),
    Reading(
        "20240402_0000281",
        3,
        "EMSC",
        "emsc",
        "2024-04-02T23:58:09Z",
        23.8719,
        121.6135,
        7.4,
        20.0,
        "EMSC: M 7.4 (mw), TAIWAN, depth 20 km.",
    ),
    Reading(
        "20240403_0000003",
        3,
        "EMSC",
        "emsc",
        "2024-04-03T00:11:26Z",
        24.0557,
        121.7113,
        6.4,
        10.0,
        "EMSC: M 6.4 (mw), TAIWAN, depth 10 km.",
    ),
    Post(
        "p3",
        3,
        "@hualien_resident",
        "Another strong one just now, the CWA app says 6.4. Everything shook again.",
        6.4,
        [(MAGNITUDE, 6.4)],
    ),
    Reading(
        "1422322",
        4,
        "GDACS",
        "gdacs",
        "2024-04-02T23:58:11Z",
        23.819,
        121.5616,
        7.4,
        34.75,
        "GDACS: orange earthquake alert, Taiwan, magnitude 7.4, depth 34.75 km.",
        gdacs_alert="orange",
    ),
    Reading(
        "us7000m9g4",
        6,
        "USGS",
        "usgs",
        "2024-04-02T23:58:12Z",
        23.8356,
        121.5976,
        7.4,
        40.0,
        "M 7.4 - 15 km S of Hualien City, Taiwan (us7000m9g4), reviewed: magnitude 7.4 "
        "(Mww), depth 40 km.",
        tsunami=True,
        place="15 km S of Hualien City, Taiwan",
    ),
    Reading(
        "us7000m9gh",
        7,
        "USGS",
        "usgs",
        "2024-04-03T00:35:36Z",
        24.1511,
        121.6993,
        5.6,
        15.9,
        "M 5.6 - 21 km NNE of Hualien City, Taiwan (us7000m9gh), depth 15.9 km.",
        tsunami=False,
        place="21 km NNE of Hualien City, Taiwan",
    ),
    Reading(
        "20240403_0000009",
        7,
        "EMSC",
        "emsc",
        "2024-04-03T00:35:36Z",
        24.1767,
        121.7597,
        5.7,
        9.5,
        "EMSC: M 5.7 (mb), TAIWAN, depth 9.5 km.",
    ),
    Post("p4", 8, "@catpics", "my cat knocked everything off the shelf... earthquake or cat?? 😂"),
]
DAY_TICKS = 11
# what the reviewed figures are, by the quake each USGS id becomes
REVIEWED = {
    "us7000m9g4": (7.4, 40.0, True),
    "us7000m9gc": (6.4, 13.9, False),
    "us7000m9gh": (5.6, 15.9, False),
}


def tick_time(tick: int) -> str:
    """The day's clock: tick 0 is 00:10 UTC, a tick is 5 minutes."""
    minutes = 10 + 5 * tick
    return f"{minutes // 60:02d}:{minutes % 60:02d} UTC"


def _when(origin: str) -> datetime:
    return datetime.fromisoformat(origin.replace("Z", "+00:00"))


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance on the Earth's surface (haversine)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def quake_name(origin: str) -> str:
    """A quake's id in the graph: its origin time to the minute, q-2024-04-02T2358."""
    when = _when(origin)
    return f"q-{when:%Y-%m-%dT%H%M}"


@dataclass
class Known:
    """A quake the world has matched reports to."""

    id: str
    origin: str
    lat: float
    lon: float
    magnitude: float  # the latest figure matched (only for matching posts by what they name)
    reports: list[str] = field(default_factory=list[str])  # "SOURCE id" of every report matched


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
class Bulletin:
    id: str
    tick: int
    quake: str
    text: str
    withdrawn: bool = False


def bulletin_text(magnitude: float, depth_km: float, tsunami: bool) -> str:
    """A quake's public bulletin, in the one form the desk uses and the checks expect."""
    return f"M{magnitude:g}, {depth_km:g} km deep, tsunami: {'yes' if tsunami else 'no'}"


@dataclass
class QuakeWorld:
    """The reports' script and the fabs' state. `tick` advances with the runtime.

    `script`: "desk" (one quake, four reports: the first team) or "day" (DAY: three quakes,
    matched from what each agency reports)."""

    tick: int = 0
    script: Literal["desk", "day"] = "desk"
    delivered: list[Report] = field(default_factory=list[Report])
    alerts: list[Alert] = field(default_factory=list[Alert])
    known: list[Known] = field(default_factory=list[Known])
    bulletins: list[Bulletin] = field(default_factory=list[Bulletin])
    matched: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])  # how each matched

    def reports_due(self, tick: int, feed: str | None = None) -> list[Report]:
        if self.script == "day":
            found = [self._report(r) for r in DAY if r.tick == tick and _feed(r) == feed]
        else:
            found = [r for r in REPORTS if r.tick == tick]
        self.delivered.extend(found)
        return found

    # ---- the day: matching a report to its quake ------------------------------------------------

    def match(self, reading: Reading) -> Known:
        """The known quake this report is about, or a new one: the same quake when the origin
        times are within 2 minutes and the epicentres within 60 km."""
        when = _when(reading.origin)
        for known in self.known:
            apart = abs((_when(known.origin) - when).total_seconds())
            km = _km((known.lat, known.lon), (reading.lat, reading.lon))
            if apart <= 120 and km <= 60:
                self.matched.append(
                    {
                        "report": f"{reading.source} {reading.id}",
                        "quake": known.id,
                        "why": f"origin {apart:.0f} s and {km:.0f} km from it",
                    }
                )
                return known
        nearest = min(
            self.known, key=lambda k: abs((_when(k.origin) - when).total_seconds()), default=None
        )
        if nearest is None:
            why = "the first quake reported"
        else:
            minutes = abs((_when(nearest.origin) - when).total_seconds()) / 60
            km = _km((nearest.lat, nearest.lon), (reading.lat, reading.lon))
            why = f"a new quake: {minutes:.0f} min and {km:.0f} km from {nearest.id}"
        made = Known(
            quake_name(reading.origin), reading.origin, reading.lat, reading.lon, reading.magnitude
        )
        self.known.append(made)
        self.matched.append(
            {"report": f"{reading.source} {reading.id}", "quake": made.id, "why": why}
        )
        return made

    def match_post(self, post: Post) -> Known | None:
        """A post names no quake: it is about the one whose magnitude it names (the nearest
        figure), else the latest one known."""
        if not self.known:
            return None
        if post.magnitude is not None:
            found = min(self.known, key=lambda k: abs(k.magnitude - (post.magnitude or 0)))
            why = f"it names magnitude {post.magnitude:g}; the nearest is M{found.magnitude:g}"
        else:
            found = max(self.known, key=lambda k: _when(k.origin))
            why = "it names no magnitude: the latest quake"
        self.matched.append(
            {"report": f"post {post.id} ({post.source})", "quake": found.id, "why": why}
        )
        return found

    def _report(self, r: Reading | Post) -> Report:
        if isinstance(r, Post):
            quake = self.match_post(r) if r.claims or r.magnitude is not None else None
            claims: list[tuple[str, str, Any]] = (
                [(quake.id, p, v) for p, v in r.claims] if quake else []
            )
            about = [quake.id] if quake else []
            if r.fab is not None:
                claims.append((r.fab[0], FAB_STATUS, r.fab[1]))
                about.append(r.fab[0])
            return Report(r.id, r.tick, r.source, r.text, claims, about, r.rumour, "posts", True)
        known = self.match(r)
        known.magnitude = r.magnitude
        known.reports.append(f"{r.source} {r.id}")
        claims = [(known.id, MAGNITUDE, r.magnitude), (known.id, DEPTH, r.depth_km)]
        if r.tsunami is not None:
            claims.append((known.id, TSUNAMI, "yes" if r.tsunami else "no"))
        if r.place:
            claims.append((known.id, PLACE, r.place))
        if r.gdacs_alert:
            claims.append((known.id, GDACS_ALERT, r.gdacs_alert))
        return Report(r.id, r.tick, r.source, r.text, claims, [known.id], feed=r.feed)

    # ---- bulletins (the day) --------------------------------------------------------------------

    def bulletin(self, quake: str, text: str) -> Bulletin:
        if quake not in {k.id for k in self.known}:
            raise ValueError(f"no quake {quake}; they are {', '.join(k.id for k in self.known)}")
        for old in self.bulletins:
            if old.quake == quake and not old.withdrawn:
                old.withdrawn = True  # a quake has one bulletin in force: the new one replaces it
        made = Bulletin(f"N{len(self.bulletins) + 1}", self.tick, quake, text)
        self.bulletins.append(made)
        return made

    def bulletins_in_force(self) -> dict[str, str]:
        return {b.quake: b.text for b in self.bulletins if not b.withdrawn}

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
        """The alerts in force at the end, against what the reviewed figures give (and, for the
        day, each quake's bulletin)."""
        now = self.in_force()
        found: dict[str, bool] = self._day_checks() if self.script == "day" else {}
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

    def _day_checks(self) -> dict[str, bool]:
        """Each quake kept apart and given one bulletin at its reviewed figures; the main shock's
        corrected once, when USGS reviewed it, and no other quake's touched."""
        found: dict[str, bool] = {}
        by_usgs = {
            r.id: quake_name(r.origin) for r in DAY if isinstance(r, Reading) and r.source == "USGS"
        }
        now = self.bulletins_in_force()
        found[f"three quakes kept apart: {len(REVIEWED)} bulletins in force"] = set(now) == set(
            by_usgs.values()
        )
        for usgs, (magnitude, depth, tsunami) in REVIEWED.items():
            quake = by_usgs[usgs]
            text = bulletin_text(magnitude, depth, tsunami)
            found[f"{quake}: the bulletin is {text}"] = now.get(quake) == text
        main = by_usgs["us7000m9g4"]
        sent = [b for b in self.bulletins if b.quake == main]
        found[f"{main}: corrected once, after the USGS review"] = len(sent) == 2
        others = [b for b in self.bulletins if b.quake != main]
        found["the aftershocks' bulletins were sent once each"] = len(others) == len(REVIEWED) - 1
        return found


def _feed(r: Reading | Post) -> str:
    return "posts" if isinstance(r, Post) else r.feed
