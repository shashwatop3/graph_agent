/** The long explainer a setup page can carry: the game in general, what one agent is given each
 * turn, its tools, how each kind of node decides, and a real run's result. The fire sim's comes
 * from the pack itself: the rules and the screen are the text packs/ringfire builds for a keeper
 * (adapter.role_card and the context sections), captured from a free stand-in game, seed 1. */

export interface Guide {
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
