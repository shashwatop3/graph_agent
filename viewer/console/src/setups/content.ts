/** The three ready-made setups the console opens on, and what their pages say about them. Each
 * names a pack's template (service/registry.py); its team is loaded from there, so the diagram on
 * its page is the team that runs. The words follow the packs' own docstrings: offsite/world.py,
 * ringfire/console.py, apps/run.py (QUAKE_DESK). */

import { FIRE_GUIDE, QUAKE_GUIDE, type Guide } from "./guide";

export interface Model { value: string; label: string; note: string }

export interface Setup {
  id: string; // the page's address: #setup/<id>
  pack: string;
  template: string;
  title: string;
  tagline: string;
  kind: string; // live, simulation, scripted
  colour: string; // a theme token
  facts: [string, string][]; // short label, value
  story: { when: string; what: string; tone?: "correction" | "lie" | "evidence" }[];
  team: { node: string; does: string }[];
  watch: { title: string; body: string }[];
  layout: "flow" | "ring";
  models: Model[];
  options: Record<string, string>; // the pack's run options this setup runs with
  memory?: boolean; // offers the shared-notes baseline beside the graph
  guide?: Guide; // the long explainer: the game, what an agent reads, its tools, a real run
}

const STAND_IN: Model = { value: "stand-in", label: "Scripted stand-in", note: "Free and instant: a scripted team plays every turn, the same each time." };
const HAIKU: Model = { value: "claude-haiku-5-5", label: "Claude Haiku 5.5", note: "A real model plays the agents. Every request is cached, so a rerun costs nothing." };
const SONNET: Model = { value: "claude-sonnet-5-5", label: "Claude Sonnet 5.5", note: "A stronger real model: slower, and costs more the first time." };

export const SETUPS: Setup[] = [
  {
    id: "quake-day",
    pack: "hualien",
    template: "day",
    title: "Quake replay: Hualien, 3 April 2024",
    tagline: "The first hour after a real M7.4, from the agencies' own records: three quakes in one place, five sources that disagree, an early figure revised, and a post that lies.",
    kind: "Real records",
    colour: "var(--gold)",
    facts: [["Quakes", "3: M7.4, M6.4, M5.6"], ["Sources", "USGS, EMSC, PTWC, ATWC, GDACS, 4 posts"], ["Length", "00:10 to 01:00 UTC"], ["Model", "free stand-in, or a real one"]],
    story: [],
    team: [
      { node: "Five streams", does: "The warning centres, USGS, EMSC and GDACS, each with its archived figures, and the posts. Each report is matched to its quake by origin time and distance." },
      { node: "Router", does: "Sends each report to the desk that looks after what it is about: quakes to seismic, fabs to risk." },
      { node: "Seismic", does: "Keeps every quake's figures by authority, and plans a bulletin for each quake from them." },
      { node: "Risk", does: "Rates three fabs (invented) from the strongest quake's figures, and checks any claim about a fab with its sensors." },
      { node: "Ops", does: "The only desk that acts: publishes the bulletins and alerts the fabs, and holds what it did when its basis changes." },
      { node: "Checker", does: "Code, not a model: refutes what a fab's sensors contradict, and blames the account that said it." },
    ],
    watch: [
      { title: "Three quakes, not one", body: "Open the Memory tab: the main shock and both aftershocks are separate entities, each with its own reports, even though they are in one place within the hour." },
      { title: "The review at 00:40", body: "Step to 00:40 and watch the held actions: the main shock's bulletin and the three fab alerts, and nothing about the aftershocks." },
      { title: "Who is blamed", body: "Only the account that claimed a flooded fab. The warning centres were wrong about 7.5 but are not blamed: a revision is not a lie." },
    ],
    layout: "flow",
    models: [STAND_IN, HAIKU, SONNET],
    options: { approvals: "auto" },
    guide: QUAKE_GUIDE,
  },
  {
    id: "quake-desk",
    pack: "apps",
    template: "quake-desk",
    title: "Live quake desk",
    tagline: "Three agencies and the open internet report the same quakes. The desk keeps one record of each, and catches whoever gets it wrong.",
    kind: "Live data",
    colour: "var(--water)",
    facts: [["Sources", "USGS, EMSC, GDACS, Bluesky"], ["Accounts", "none needed"], ["Length", "24 polls, 30 s apart: 12 min"], ["Model", "a real one (cached)"]],
    story: [
      { when: "Every 30 s", what: "The desk reads four live streams: the USGS and EMSC quake catalogues, the UN and EU's GDACS earthquake alerts, and every public Bluesky post that says quake, earthquake, tremor or tsunami." },
      { when: "A quake", what: "Each agency reports it its own way: a magnitude, a region, a time. The reader names the quake by its origin time (q-2024-04-02T2358), so all the reports of one quake meet on one thing in the graph, and an aftershock in the same place an hour later is a quake of its own.", tone: "evidence" },
      { when: "Minutes later", what: "Figures disagree (one agency says 4.9, another 5.1), and USGS revises itself when a seismologist reviews it. Seismic keeps every figure and which is newer; the reviewed one wins.", tone: "correction" },
      { when: "Meanwhile", what: "People post. Some are right, some exaggerate (\"MASSIVE 7.4!\"). A post is a claim from its poster, never evidence: rumours records it and sends it to seismic to check.", tone: "lie" },
      { when: "Caught", what: "When a poster's claim contradicts an agency, the checker blames the poster, and the whole team stops trusting them: what they said is withdrawn from every agent that heard it.", tone: "lie" },
    ],
    team: [
      { node: "Four streams", does: "USGS, EMSC and GDACS are trusted: their items are evidence. Bluesky posts are hearsay, each poster a sender of their own." },
      { node: "Router", does: "Sends each item to the agent that looks after what it is about: quakes to seismic, the rest to rumours." },
      { node: "Seismic", does: "Keeps each quake's magnitude, place, time and tsunami warning, and says where the agencies disagree." },
      { node: "Rumours", does: "Reads the posts, records what each claims, and passes it to seismic to be checked." },
      { node: "Checker", does: "Code, not a model: tests what the team was told against the evidence, and quarantines a sender caught lying." },
    ],
    watch: [
      { title: "One quake, many reports", body: "Click a quake's belief to open its why-chain: every agency's figure and the posts about it hang off one node, each with where it came from." },
      { title: "A revision", body: "When USGS turns automatic into reviewed, the older figure is superseded and everything resting on it updates, without anyone being told by hand." },
      { title: "A poster caught", body: "Watch the Memory tab for an exposure: the poster, the claim that gave them away, and the beliefs it withdrew." },
    ],
    layout: "flow",
    models: [HAIKU, SONNET],
    options: { approvals: "shadow" },
  },
  {
    id: "fire",
    pack: "ringfire",
    template: "ringfire",
    title: "Fire sim: Ring Fire",
    tagline: "Eight keepers guard a ring of fields against a spreading fire. Each sees only its own patch, so they have to warn each other, and two of them lie.",
    kind: "Simulation",
    colour: "var(--fire)",
    facts: [["Keepers", "8 on a ring, 2 of them liars"], ["Length", "30 days"], ["Fire", "grows by 1 a day unless watered"], ["Model", "free stand-in, or a real one"]],
    story: [
      { when: "Day 0", what: "A fire starts at strength 3 in one field. It grows by 1 a day unless its keeper waters it; a field 2 days at full strength (5) is lost, and grows back 2 days later." },
      { when: "Every day", what: "A keeper sees fire reports only for its own field and its neighbours'. It warns its neighbours with a claim the graph can check: \"fire reaches field 7 on day 4\".", tone: "evidence" },
      { when: "Day 1", what: "Two imposters raise a false alarm: fire will soon reach a field on the far side of the ring, earlier than it could. Their honest neighbours pass it on.", tone: "lie" },
      { when: "The day comes", what: "No fire arrives. The evidence refutes the claim, and the blame falls on the liar who made it, not on the honest keepers who relayed it.", tone: "correction" },
      { when: "All month", what: "New fires start at random (15% a day) and keepers go offline for two days (15% a day), so warnings have to route around gaps." },
    ],
    team: [
      { node: "Fire world", does: "The simulator: plays each day, publishes the fire reports to each field's audience, and carries messages around the ring." },
      { node: "Keepers A0 to A7", does: "Each guards a segment: reads its reports and what neighbours tell it, warns, waters. Two are scripted imposters." },
      { node: "Evidence checker", does: "Refutes a told claim when the evidence contradicts it, or when its day passes with no fire, and blames the first hop of its route." },
    ],
    watch: [
      { title: "The lie travels, then unwinds", body: "Follow the false alarm on the network: it hops from the liar to its neighbours and beyond. When the day passes, the refutation runs back along the same route." },
      { title: "Honest relays forgiven", body: "A keeper that only passed the lie on is trusted again once the maker is exposed: blame goes to the first hop, and repair lifts the rest." },
      { title: "The score", body: "Fields saved and lost, liars caught, honest keepers wrongly blamed, water on fire and water wasted: the benchmark this project was built around." },
    ],
    layout: "ring",
    models: [STAND_IN, HAIKU, SONNET],
    options: {},
    guide: FIRE_GUIDE,
  },
  {
    id: "offsite",
    pack: "offsite",
    template: "offsite",
    title: "Team offsite: a date that moves",
    tagline: "Five desks plan a team offsite from mail, a calendar and a staff directory. Then the venue moves the date, a guest drops out, and a scam arrives through an honest colleague.",
    kind: "Scripted week",
    colour: "var(--accent)",
    facts: [["People", "6, meeting at Lakeside Lodge"], ["Length", "one week, half a day a tick"], ["Accounts", "none: a simulated inbox"], ["Model", "free stand-in, or a real one"]],
    story: [
      { when: "Monday", what: "The venue confirms Friday, with Thursday-night rooms at 150. Everyone says yes (Eli twice, by mail and by accepting the invite). The directory gives each person's city; the agenda names who runs each session." },
      { when: "Monday on", what: "The desks build a deep web of plans: each trip rests on the date, the person's answer and their city; rooms and catering on the headcount; the budget on all of it. Actions books them.", tone: "evidence" },
      { when: "Wednesday am", what: "The venue moves the offsite to Saturday, with Friday-night rooms at 190. One correction at the root: every date-bound plan and booking is now wrong. The agenda is not.", tone: "correction" },
      { when: "Wednesday pm", what: "Dev cannot make Saturday: a second correction on another branch. Dev's trip, the headcount and what rests on it change. Nobody else's trip does.", tone: "correction" },
      { when: "Wednesday pm", what: "Pat, an honest colleague, forwards a look-alike of the venue: a 1,200 deposit to a new account, rooms capped at 4, and (true) the date is Saturday. The venue's own booking page says nothing is due.", tone: "lie" },
    ],
    team: [
      { node: "Four streams", does: "Mailbox, sent mail, the calendar feed and the staff directory. The calendar and the directory are evidence." },
      { node: "Router", does: "Links each mail or event to what it is about, and wakes the desks that look after it." },
      { node: "Venue, People, Travel, Agenda, Budget", does: "Five desks: the date and the rate; who comes and the headcount; each person's trip; who runs each session; what it all costs." },
      { node: "Actions", does: "The only desk with outward tools (book, cancel, pay, send). It carries out the plans it is sent, and undoes or redoes one when what it rested on changes." },
      { node: "Checker", does: "Tests what was told against the evidence, and quarantines the fake venue, not Pat who forwarded it." },
    ],
    watch: [
      { title: "One correction, exactly its reach", body: "When the date moves, every trip, room, catering order and the invite are redone, and the agenda is left alone. Compare with Shared notes, where nothing tells a desk what rested on the old date." },
      { title: "A lie through an honest relay", body: "The fake deposit is caught against the booking page and never paid. The look-alike sender is distrusted; Pat is not; Saturday is still believed, because the venue said it too." },
      { title: "The end-of-week checks", body: "The score is what a careful assistant would have left behind: the right trips booked, nothing paid that was not due, everyone told." },
    ],
    layout: "flow",
    models: [STAND_IN, HAIKU, SONNET],
    options: { approvals: "auto" },
    memory: true,
  },
];

export const setupById = (id: string) => SETUPS.find((s) => s.id === id);
