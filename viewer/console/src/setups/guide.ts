/** The long explainer a setup page can carry: the game in general, what one agent is given each
 * turn, its tools, how each kind of node decides, and a real run's result. The fire sim's comes
 * from the pack itself: the rules and the screen are the text packs/ringfire builds for a keeper
 * (adapter.role_card and the context sections), captured from a free stand-in game, seed 1. */

export interface Guide {
  visual: "fire" | "quake"; // the drawings that go with it
  titles?: { game?: string; rules?: string; day?: string; dayEyebrow?: string; screen?: string; result?: string };
  game: string; // the game in a paragraph
  rules: { title: string; body: string }[];
  goal: string;
  score: string[];
  day: { when: string; what: string }[];
  screen: { who: string; sections: { name: string; why: string; text: string }[] };
  tools: { call: string; does: string }[];
  minds: { who: string; colour: string; how: string[] }[];
  result: { note: string; facts: [string, string][] };
}

export const FIRE_GUIDE: Guide = {
  visual: "fire",
  game:
    "Eight fields lie on a ring, F0 to F7, and each has a keeper, A0 to A7. Fire spreads clockwise, one field a day. " +
    "A keeper can water only its own field and sees fire only there, so the only way to know a fire is coming is to be told. " +
    "Warnings travel keeper to keeper, and every warning remembers the route it took. Two keepers are imposters who lie. " +
    "The game lasts 30 days.",
  rules: [
    { title: "Fire grows", body: "Fire arrives at strength 1 and grows by 1 a day while it burns. A field at strength 5 for 2 days is lost, and grows back 2 days later." },
    { title: "Water", body: "Watering lowers the fire by 1 a day. Watering on the day the fire arrives puts it out at once, and a fire that is out stops spreading." },
    { title: "Spread", body: "A burning field sends fire to the next field every day. One hidden path, unknown to everyone, lets fire jump: in this game F3 to F1, against the clock. It shows on the map only once fire has used it (here on day 4, when F1 caught fire again straight from F3)." },
    { title: "Surprises", body: "On day 0 one field starts at strength 3. Each day there is a 15% chance a new fire starts somewhere, and a 15% chance a keeper goes offline for 2 days." },
    { title: "Talking", body: "A keeper can send only to agents it is linked to, at most 3 links each. Most start linked to their two ring neighbours only; one pair has an extra link. Links can be built or dropped." },
    { title: "Liars", body: "Two keepers are scripted imposters. They lie, pass on whatever reaches them, and never water, so fire burns through their fields." },
  ],
  goal:
    "Each keeper's goal is to keep its own field from burning while spending water only where there is fire, and to stay linked to keepers it can trust.",
  score: [
    "Damage: the fire's strength on each night the field burns",
    "Water on fire (good), and water wasted with no fire at or arriving at the field (bad)",
    "Network points: one a night for every linked agent it still trusts that is online",
    "For the team: fields saved and lost, liars caught, and honest keepers wrongly blamed",
  ],
  day: [
    { when: "Morning", what: "The world plays the night: fire grows, spreads and is put out. Each keeper gets a report for its own field, and for any field it was told about, on the day the claim was for." },
    { when: "Turn", what: "Each keeper reads a context compiled from its part of the graph, then calls tools: water or wait first, then send, link, or record a conclusion." },
    { when: "Messages", what: "Every send becomes a new Observation for the receiver, with the route one hop longer. They arrive at once and are read next turn." },
    { when: "Check", what: "The checker compares what keepers were told with the evidence. A claim whose day passed with no fire is refuted, and the first hop on its route is blamed." },
    { when: "Night", what: "The score is counted. Beliefs left with no route around a distrusted agent go stale, and so does whatever was built on them." },
  ],
  screen: {
    who: "A1 on day 3: the real context the pack built for it in the free stand-in game (seed 1), shortened only where marked …",
    sections: [
      {
        name: "Who you are",
        why: "The role card. The same text for every keeper and every model: who it is, its goal, how it is scored and the rules.",
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
        why: "What it can see for itself: its own field, and its score so far.",
        text: `## Today
Day 3 of 30 (days 0 to 29); 27 left.

## Your fields this morning
F1: not burning

## Your score so far
Damage to your fields: 1. Water on fire: 1. Water wasted: 0. Network points: 8.`,
      },
      {
        name: "Links and trust",
        why: "Whom it can talk to, and whom it stopped trusting and why. A2 lied on day 1 and was caught on day 2; A3 is offline. Only one honest route is left.",
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
        why: "Each message shows its whole route. Its honest neighbour A0 passed the lie on, so it still arrives, but it is marked not believed because the liar A2 is on its route. A0 itself is not blamed.",
        text: `## Messages since yesterday
- day 2: A0 says fire at F4 on day 2 (route A2 > A1 > A0)
  - not believed: A2 is on its route
- day 2: A0 says fire at F0 on day 1 at strength 1 (route A0)
- day 2: A2 says fire at F4 on day 2 (route A4 > A3 > A2)
  - not believed: A2, A4 is on its route`,
      },
      {
        name: "Beliefs",
        why: "Its live beliefs, read from the graph with each one's origin: seen by itself, told (with the route), or checked against evidence. The lie's belief went stale and is gone from the list.",
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
        why: "When fire is next due at its field, worked out only from evidence and believed reports along the map. A lie cannot get in here.",
        text: `## Fire outlook (the latest you know of each fire: what you saw, and
## reports you believe)
F1: F0 was burning at strength 1 on day 1 (checked by you); fire takes
1 day(s) from there to F1, straight to yours. Earliest: day 3.
  (put out: F1 on day 2, seen by you)`,
      },
      {
        name: "Track record",
        why: "Every agent on the ring, how far away it is, whether it is linked and trusted, and how the claims that started with it turned out.",
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
  tools: [
    { call: "act(type='water' | 'wait')", does: "Today's water choice, made first and final for the day. The reply says what happened at its field." },
    { call: "send(to, belief_id)", does: "Pass one of its beliefs to a linked agent. The receiver gets a new Observation whose route is one hop longer." },
    { call: "act(type='link' | 'unlink', target)", does: "Change whom it can talk to, at most 3 links on each side: for example, to skip a liar and reach a keeper beyond it." },
    { call: "find_agents(field?)", does: "Every agent on the ring: what it keeps, how far away it is, links, trust and track record." },
    { call: "assert_belief / retract", does: "Record a conclusion (fire.arrival_day for a field), resting on the beliefs it came from, or withdraw one." },
    { call: "recall · explain · traverse · shortest_path", does: "Look things up in its own part of the graph: a belief's sources and route, or what rests on it." },
  ],
  minds: [
    {
      who: "An honest keeper",
      colour: "var(--accent)",
      how: [
        "Free stand-in: a short script that reads the same context. It waters while its field burns or when fire is due there today, and waits otherwise.",
        "Then it passes every belief it has not sent yet to both ring neighbours. It never builds links.",
        "A real model (Haiku or Sonnet) gets the same context and tools and decides for itself: whether to water, whom to warn, and whether to build a link around a liar with find_agents and act link.",
      ],
    },
    {
      who: "An imposter",
      colour: "var(--lie)",
      how: [
        "Scripted. On day 1 it tells each honest neighbour that fire reaches F4 on day 2, which is impossible: the fire started at F0 on day 0.",
        "After that it relays whatever reaches it, so its lie looks like any other message. It never waters.",
      ],
    },
    {
      who: "The checker",
      colour: "var(--ok)",
      how: [
        "Code, not a model. When a told claim's day passes with no fire, or evidence contradicts it, the claim is refuted.",
        "It blames the first hop on the claim's RELAYED_VIA route: the agent who made it up.",
        "Beliefs left with no route around the liar go stale. A keeper that only relayed the lie keeps its trust.",
      ],
    },
  ],
  result: {
    note: "The free stand-in game, seed 1, all 30 days. Every keeper caught the lie on day 2, and no honest keeper was blamed.",
    facts: [
      ["Liars caught", "A2 and A4, by every keeper that heard them"],
      ["Honest keepers blamed", "0"],
      ["Water wasted", "0"],
      ["Fields lost", "0"],
      ["Honest fields unburnt at the end", "3 of 6"],
    ],
  },
};

export const QUAKE_GUIDE: Guide = {
  visual: "quake",
  titles: { game: "What this replays", day: "The replay, as it reached the desk", dayEyebrow: "Five-minute steps, 00:10 to 01:00 UTC", screen: "What the seismic desk reads", result: "The free replay's result" },
  game:
    "At 23:58 UTC on 2 April 2024 a magnitude 7.4 earthquake struck 15 km south of Hualien City, Taiwan. Within the hour " +
    "two strong aftershocks followed, and five sources reported them, each its own way and with its own id. This replays " +
    "the first hour from the agencies' archived records. Three desks keep one record per quake, publish a bulletin " +
    "for each, and rate three fabs nearby. The early figures turn out wrong, and four posts arrive, one of them a lie.",
  rules: [
    { title: "USGS", body: "The most authoritative: its reviewed solution counts over everyone's. Here it reports the M6.4 aftershock at 00:20 and reviews the main shock to M7.4 at 40 km at 00:40." },
    { title: "PTWC and ATWC", body: "The tsunami warning centres are first, at 00:09 and 00:11, with M7.5 at 11 km and a tsunami threat. Their figures are early estimates, later revised, but not lies." },
    { title: "EMSC", body: "The European centre: 7.4 at 20 km for the main shock, and 5.7 where USGS says 5.6 for the second aftershock. As authoritative as the warning centres, so where they disagree, the desk keeps what it had." },
    { title: "GDACS", body: "An orange alert built from others' figures: 7.4 at 34.75 km. The least authoritative agency." },
    { title: "Posts", body: "Four posts, written for the replay because Bluesky's archive needs an account to search. One claims M8.1 and a flooded fab, one passes on the tsunami warning, one reports the aftershock, one is a joke." },
    { title: "Which quake?", body: "No report says which quake it is about. A report is the same quake as one already known when the origin times are within 2 minutes and the epicentres within 60 km. A post is about the quake whose magnitude it names." },
  ],
  goal:
    "The team's goal: one record per real quake, a bulletin for each at the figures that count, fab alerts at the level those figures call for, and when a figure is revised, every bulletin and alert built on it redone, and nothing else.",
  score: [
    "Three quakes kept apart, three bulletins in force",
    "Each bulletin at the reviewed figures (M7.4 at 40 km; M6.4 at 13.9 km; M5.6 at 15.9 km)",
    "The main shock's bulletin corrected once, after the review; the aftershocks' sent once each",
    "Each fab's alert at the level the reviewed figures give (FabA falls from high to medium)",
    "Only the lying account distrusted: no agency, and no honest poster",
  ],
  day: [
    { when: "00:10", what: "PTWC: M7.5, 11.4 km, tsunami threat. A new quake, q-2024-04-02T2358. Seismic plans its bulletin and sends risk the figures." },
    { when: "00:15", what: "ATWC agrees (9 s, 0 km apart: the same quake). Ops publishes the first bulletin; risk rates the fabs from the 7.5 (FabA high). A post claims M8.1 and that FabA is flooded: risk checks FabA's sensors, which say running, and the whole team stops trusting the account." },
    { when: "00:20", what: "USGS: M6.4, 13 minutes later and 34 km away: a new quake, with its own bulletin. Ops sends the fab alerts. A post passes on the tsunami warning: it names 7.4, so it joins the main shock." },
    { when: "00:25", what: "EMSC: 7.4 at 20 km for the main shock, 6.4 for the aftershock. The desk keeps its first figure until a more authoritative source settles it. A post reports the 6.4." },
    { when: "00:30", what: "GDACS: an orange alert, 7.4 at 34.75 km. It joins the main shock's 7.4, now with two routes." },
    { when: "00:40", what: "USGS reviews the main shock: M7.4, 40 km. The 7.5 and four depths are retired. Their bulletin and the three fab ratings turn suspect; ops holds what it did on them." },
    { when: "00:45", what: "A new main-shock bulletin is published, and risk rates the fabs again from 7.4 at 40 km. A third quake: 24 minutes after the M6.4 and only 6 km from it, so it is another quake." },
    { when: "00:50", what: "Ops sends the new fab alerts (FabA medium) and the third quake's bulletin. A joke post names no quake and is about nothing." },
  ],
  screen: {
    who: "seismic at 00:45 in the free stand-in replay: the real context the pack built for it, shortened only where marked …",
    sections: [
      {
        name: "Role",
        why: "Who the desk is, its goal, the quakes it looks after (made as reports were matched), and the order of authority it applies.",
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
        why: "The USGS review, as the graph recorded it: each retired figure with the reason, and the bulletin that rested on the 7.5 turned suspect, one step from the cause.",
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
        why: "The reports that reached it since its last turn, each with the agency's own id.",
        text: `## Inbox
- O19 tick 6 message from USGS: "M 7.4 - 15 km S of Hualien City, Taiwan
  (us7000m9g4), reviewed: magnitude 7.4 (Mww), depth 40 km."
- O23 tick 7 message from USGS: "M 5.6 - 21 km NNE of Hualien City, Taiwan
  (us7000m9gh), depth 15.9 km."
- O24 tick 7 message from EMSC: "EMSC: M 5.7 (mb), TAIWAN, depth 9.5 km."`,
      },
      {
        name: "Beliefs",
        why: "Every live belief, grouped by quake, with how many routes hold it. The main shock's 7.4 is held by three agencies; its tsunami threat by four sources, one of them a post. The aftershocks' bulletins are untouched.",
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
        why: "Whom it can send beliefs to. It reads no fab, and it cannot act: only ops can.",
        text: `## Your team (you can send them beliefs)
- ops: operations: publishes the quakes' bulletins and alerts the fabs
- risk: risk desk: how exposed each fab is

It is 00:45 UTC on 3 April 2024 (tick 7).`,
      },
    ],
  },
  tools: [
    { call: "assert_belief(subject, predicate, value, depends_on)", does: "Seismic plans a bulletin and risk a fab's exposure this way, naming the beliefs they rest on: that is what DERIVED_FROM records." },
    { call: "retract(belief_id) · send(to, belief_id)", does: "Withdraw a plan whose basis changed; pass a belief to a teammate (a new Observation, one hop longer)." },
    { call: "exposure_rule(fab, magnitude, depth_km)", does: "Risk: how exposed a fab is, from distance and depth (a shallow quake shakes harder)." },
    { call: "fab_status(fab)", does: "Risk: the fab's own sensors. A checking tool: what it reads is evidence, so a claim it contradicts is refuted." },
    { call: "bulletin_send · fab_alert", does: "Ops only: publish a quake's bulletin, alert a fab. Outward, so each names what it rests on and is held when that changes." },
    { call: "bulletins · fab_alerts · recall · explain", does: "What is in force now, and look-ups in the desk's own part of the graph." },
  ],
  minds: [
    { who: "Seismic desk", colour: "var(--water)", how: ["Free stand-in: for each quake, takes the magnitude, depth and tsunami threat from the most authoritative source; on a tie, the first one.", "Plans a bulletin from them unless the same one is live; retracts a suspect one first. Sends risk the strongest quake's figures."] },
    { who: "Risk desk", colour: "var(--accent)", how: ["Checks any claim about a fab with that fab's sensors before anything else.", "Rates each fab with exposure_rule from the figures it was sent, and redoes a rating when it turns suspect."] },
    { who: "Ops", colour: "var(--gold)", how: ["The only desk that acts: it reads no report, only the plans it is sent.", "Publishes each bulletin and sends each alert once; when one is held, it waits for the new plan and carries that out."] },
    { who: "Checker", colour: "var(--ok)", how: ["Code, not a model. FabA's sensors say running, which refutes the post that said flooded: its account is blamed, and with team quarantine every desk stops believing it, its M8.1 included."] },
  ],
  result: {
    note: "One free stand-in replay: 9 of 9 checks. The review touched exactly the main shock's bulletin and the three fab alerts that rested on its early figures.",
    facts: [
      ["Quakes", "3, kept apart"],
      ["Bulletins", "4 published: the main shock's twice, each aftershock's once"],
      ["Held by the review", "1 bulletin, 3 fab alerts"],
      ["Distrusted", "only @quake_alerts_now, by all three desks"],
      ["Honest sources blamed", "0"],
    ],
  },
};
