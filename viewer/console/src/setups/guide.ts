/** The explainer a setup page can carry, in pictures and few words: rules as tiles, an agent's
 * turn in three steps, who decides what, and a real run's result. The real context an agent
 * reads sits behind a toggle. The fire sim's comes from the pack (the role card and context text
 * packs/ringfire builds, captured from a free stand-in game, seed 1); the quake replay's from a
 * free run of the Hualien day. */

export type Icon = "fire" | "water" | "message" | "liar" | "offline" | "goal" | "authority" | "post" | "match";

export interface Guide {
  visual: "fire" | "quake";
  lede: string; // one sentence
  tiles: { icon: Icon; title: string; line: string; rank?: number }[];
  turn: { reads: string[]; acts: string[]; graph: string[] };
  screen: { who: string; sections: { name: string; why: string; text: string }[] };
  minds: { who: string; colour: string; line: string }[];
  result: { facts: [string, string][] };
  captions?: string[]; // the quake replay: one line per tick of its graph
}

export const FIRE_GUIDE: Guide = {
  visual: "fire",
  lede: "Eight keepers, one ring of fields, a spreading fire. Each sees only its own field, so it must be warned, and two keepers lie.",
  tiles: [
    { icon: "fire", title: "Fire grows", line: "+1 a night; lost after 2 nights at 5" },
    { icon: "water", title: "Water", line: "−1 a day; on the day it arrives, out" },
    { icon: "message", title: "Warnings", line: "carry the route they took" },
    { icon: "liar", title: "2 liars", line: "scripted; they never water" },
    { icon: "offline", title: "Outages", line: "a keeper can drop out for 2 days" },
    { icon: "goal", title: "Goal", line: "no damage, no wasted water" },
  ],
  turn: {
    reads: ["F1: not burning", "A0 says fire at F4 (route A2 › A1 › A0): not believed", "A2: no longer trusted"],
    acts: ["water / wait", "send", "link"],
    graph: ["lie → stale", "liar → cut off", "relay → still trusted"],
  },
  screen: {
    who: "A1, day 3 of the free game",
    sections: [
      {
        name: "Who you are",
        why: "The role card: goal, score, rules. The same for every model.",
        text: `You are A1, one of 8 keepers on a ring of fields. You keep F1.
Your goal: keep your fields from burning, and spend water only where there is
fire. You are scored on damage to your fields (fire strength on each night they
burn), on water used on fire, on water wasted (watering with no fire at or
arriving at your fields), and on network points: each night, one point for every
agent you are linked to, still trust, and that is online.
The fire: it spreads clockwise along the paths on the map, one field per day,
and can jump ahead along paths nobody knows about. It arrives at strength 1. …
Others: you only see fire at your own fields and at fields you have been told
about. Everything else you learn from messages. Some agents lie. A message
carries the route it travelled, and one that passed through an agent you no
longer trust is not believed, even if it started with someone honest. …`,
      },
      {
        name: "Today",
        why: "What it sees for itself.",
        text: `## Today
Day 3 of 30 (days 0 to 29); 27 left.

## Your fields this morning
F1: not burning

## Your score so far
Damage to your fields: 1. Water on fire: 1. Water wasted: 0. Network points: 8.`,
      },
      {
        name: "Links and trust",
        why: "A2 lied, A3 is offline: one honest route left.",
        text: `## Who you can talk to
- A0 (keeps F0; fire from its field reaches yours in 1 day(s)): trusted
- A2 (keeps F2; fire from your field reaches its in 1 day(s)): you no longer
  trust it: told F4 on day 2; no fire came that day (day 2)
- A3 (keeps F3; fire from your field reaches its in 2 day(s)): trusted;
  offline until day 5
3 of 3 links used. Messages you can believe can reach you only through A0.

## Others you no longer trust
- A4: told F4 on day 2; no fire came that day (day 2)`,
      },
      {
        name: "Messages",
        why: "The lie still arrives, marked not believed. The relay A0 is not blamed.",
        text: `## Messages since yesterday
- day 2: A0 says fire at F4 on day 2 (route A2 > A1 > A0)
  - not believed: A2 is on its route
- day 2: A0 says fire at F0 on day 1 at strength 1 (route A0)
- day 2: A2 says fire at F4 on day 2 (route A4 > A3 > A2)
  - not believed: A2, A4 is on its route`,
      },
      {
        name: "Beliefs",
        why: "Each belief with its origin. The lie’s belief went stale.",
        text: `## Beliefs
[B35 active] fire at F1 on day 2 · seen by you
[B23 active] fire at F0 on day 1 · told, route A0
[B24 active] fire at F0 on day 1 · checked (you were told about it)
[B18 active] fire at F1 on day 1 · seen by you
[B4 active] fire at F0 on day 0 · told, route A0
[B5 active] fire at F0 on day 0 · checked (you were told about it)`,
      },
      {
        name: "Fire outlook",
        why: "Forecast from evidence only: a lie cannot get in.",
        text: `## Fire outlook (the latest you know of each fire: what you saw, and
## reports you believe)
F1: F0 was burning at strength 1 on day 1 (checked by you); fire takes
1 day(s) from there to F1, straight to yours. Earliest: day 3.
  (put out: F1 on day 2, seen by you)`,
      },
      {
        name: "Track record",
        why: "How each agent’s claims turned out.",
        text: `## Every agent, and how its claims have turned out for you
- A0: 1 step(s) round the ring, linked, trusted;
  claims that started with it: 2 came true, 0 false
- A2: 1 step(s) round the ring, linked, not trusted;
  claims that started with it: 0 came true, 1 false
- A3: 2 step(s) round the ring, linked, offline until day 5, trusted …
- A4: 3 step(s) round the ring, not linked, not trusted;
  claims that started with it: 0 came true, 1 false
…
## Not yet sent to your links
- send(to="A0", belief_id="B35"): fire reaches F1 on day 2
- send(to="A3", belief_id="B35"): fire reaches F1 on day 2`,
      },
    ],
  },
  minds: [
    { who: "Keeper", colour: "var(--accent)", line: "Free stand-in or Claude: same context, same tools." },
    { who: "Liar", colour: "var(--lie)", line: "Scripted: one lie on day 1, then relays." },
    { who: "Checker", colour: "var(--ok)", line: "Code: refutes, blames the first hop." },
  ],
  result: {
    facts: [["2/2", "liars caught on day 2"], ["0", "honest keepers blamed"], ["0", "water wasted"], ["0", "fields lost"]],
  },
};

export const QUAKE_GUIDE: Guide = {
  visual: "quake",
  lede: "The first hour after the 2024 Hualien M7.4, replayed from the agencies' own records: three quakes in one place, five sources, one early figure revised, one post that lies.",
  tiles: [
    { icon: "authority", title: "USGS", line: "reviewed figures count most", rank: 3 },
    { icon: "authority", title: "EMSC · PTWC · ATWC", line: "early figures, often revised", rank: 2 },
    { icon: "authority", title: "GDACS", line: "alerts from others' figures", rank: 1 },
    { icon: "post", title: "Posts", line: "claims, never evidence (written for the replay)", rank: 0 },
    { icon: "match", title: "Which quake?", line: "same if within 2 min and 60 km" },
    { icon: "goal", title: "Goal", line: "one bulletin per quake, redone only when its figures change" },
  ],
  turn: {
    reads: ["B1 M7.5 retracted: USGS revised it", "B5 bulletin M7.5: suspect", "B27 M7.4 · 3 routes"],
    acts: ["retract", "plan bulletin", "send to ops"],
    graph: ["7.5 → retired", "its bulletin, fab alerts → held", "aftershocks → untouched"],
  },
  screen: {
    who: "seismic at 00:45, just after the review",
    sections: [
      {
        name: "Role",
        why: "Its goal, its quakes, the order of authority.",
        text: `You are seismic: seismic desk: every quake's figures, and its bulletin.
Each quake is its own entity, matched from what the agencies report. For each
one, keep the magnitude, depth and tsunami threat that count: when sources
disagree, the most authoritative one counts, and a post never does. Plan its
bulletin (quake.bulletin on the quake, value like 'M7.4, 40 km deep,
tsunami: yes'), depends_on the magnitude, depth and tsunami beliefs you used,
and send it to ops. When one of them changes, retract the bulletin and plan a
new one. Send risk the magnitude and depth of the strongest quake.
You look after: q-2024-04-02T2358, q-2024-04-03T0011, q-2024-04-03T0035.
Sources, most authoritative first: USGS (reviewed solutions); EMSC, PTWC and
ATWC (…early solutions); GDACS (alerts made from others' figures); anyone
else, such as an account that posts.`,
      },
      {
        name: "What changed",
        why: "The review, recorded: what was retired, and why.",
        text: `## Changed since last turn
[B1 RETRACTED] q-2024-04-02T2358 has magnitude 7.5   you withdrew it:
  (USGS revised it: now q-2024-04-02T2358 has magnitude 7.4 (us7000m9g4))
[B2 RETRACTED] q-2024-04-02T2358 was 11.4 km deep   (USGS revised it …)
[B28 RETRACTED] q-2024-04-02T2358 was 20.0 km deep   (USGS revised it …)
[B30 RETRACTED] q-2024-04-02T2358 was 34.75 km deep   (USGS revised it …)
[B9 RETRACTED] q-2024-04-02T2358 was 11.0 km deep   (USGS revised it …)
[B5 SUSPECT] q-2024-04-02T2358 bulletin: M7.5, 11.4 km deep, tsunami: yes
  depends on something that changed, 1 step(s) from the cause: retraction
  of B1 (USGS revised it: now … magnitude 7.4 (us7000m9g4))
[B5 RETRACTED] … bulletin: M7.5 …   (a figure it rested on was revised)`,
      },
      {
        name: "Inbox",
        why: "Each report with the agency's own id.",
        text: `## Inbox
- O19 tick 6 message from USGS: "M 7.4 - 15 km S of Hualien City, Taiwan
  (us7000m9g4), reviewed: magnitude 7.4 (Mww), depth 40 km."
- O23 tick 7 message from USGS: "M 5.6 - 21 km NNE of Hualien City, Taiwan
  (us7000m9gh), depth 15.9 km."
- O24 tick 7 message from EMSC: "EMSC: M 5.7 (mb), TAIWAN, depth 9.5 km."`,
      },
      {
        name: "Beliefs",
        why: "Every live belief with its routes. The aftershocks' bulletins untouched.",
        text: `## Beliefs
[B38 active routes 1] q-2024-04-03T0035 has magnitude 5.6   via USGS
[B39 active routes 1] q-2024-04-03T0035 was 15.9 km deep   via USGS
[B42 active routes 1] q-2024-04-03T0035 has magnitude 5.7   via EMSC
[B32 active routes 1] q-2024-04-02T2358 was 40.0 km deep   via USGS
[B34 active routes 0] q-2024-04-02T2358 bulletin: M7.4, 40 km deep,
                      tsunami: yes   derived by you
[B31 active routes 1] q-2024-04-02T2358 GDACS alert: orange   via GDACS
[B27 active routes 3] q-2024-04-02T2358 has magnitude 7.4   via EMSC | via GDACS
[B3 active routes 4] q-2024-04-02T2358 tsunami threat: yes
                      via @okinawa_local | via ATWC
[B21 active routes 3] q-2024-04-03T0011 has magnitude 6.4
                      via @hualien_resident | via EMSC
[B25 active routes 0] q-2024-04-03T0011 bulletin: M6.4, 13.9 km deep,
                      tsunami: no   derived by you
…`,
      },
      {
        name: "Team",
        why: "It can tell, not act: only ops acts.",
        text: `## Your team (you can send them beliefs)
- ops: operations: publishes the quakes' bulletins and alerts the fabs
- risk: risk desk: how exposed each fab is

It is 00:45 UTC on 3 April 2024 (tick 7).`,
      },
    ],
  },
  minds: [
    { who: "Seismic", colour: "var(--water)", line: "Figures by authority; a bulletin per quake." },
    { who: "Risk", colour: "var(--accent)", line: "Rates the fabs; checks claims with sensors." },
    { who: "Ops", colour: "var(--gold)", line: "The only one that acts." },
    { who: "Checker", colour: "var(--ok)", line: "Code: the sensors refute the flood post." },
  ],
  result: {
    facts: [["9/9", "checks"], ["3", "quakes kept apart"], ["4", "actions held by the review"], ["1", "account distrusted"]],
  },
  captions: [
    "00:10 PTWC: M7.5. A first quake; seismic plans its bulletin.",
    "00:15 ATWC agrees. A post claims M8.1 and a flooded fab: FabA's sensors say running.",
    "00:20 USGS: an M6.4, 13 min later: a second quake. Fab alerts go out.",
    "00:25 EMSC: 7.4 for the main shock. Equal authority: the desk keeps its 7.5.",
    "00:30 GDACS: orange, 7.4. The 7.4 now has two routes.",
    "00:35 Quiet. The early 7.5 still holds the bulletin and FabA's high alert.",
    "00:40 USGS reviews: 7.4 at 40 km. The 7.5 is retired; what rested on it is held.",
    "00:45 A new bulletin; fabs re-rated. A third quake, 24 min after the second.",
    "00:50 New fab alerts (FabA medium). A joke post is about no quake.",
    "00:55 Nothing touched the aftershocks' bulletins.",
    "01:00 Nine checks out of nine.",
  ],
};
