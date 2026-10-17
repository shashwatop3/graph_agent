// The shapes the service sends (src/graph_agent/service/app.py and spaces.py) and the team file
// (src/graph_agent/frame/spec.py). Kept in step by hand: both sides are small.

export type TriggerKind = "tick" | "schedule" | "item" | "message" | "change" | "due" | "exposure" | "approval";
export type LinkKind = "feeds" | "owns" | "talks_to" | "watches";
export type NodeKind = "source" | "code" | "model" | "scripted";

export interface Trigger { on: TriggerKind; every?: number; at?: number; within?: number; predicate?: string | null }

export interface NodeSpec {
  id: string;
  type: string;
  label?: string;
  role?: string;
  goals?: string;
  triggers?: Trigger[];
  tools?: string[];
  graph_tools?: string[] | null;
  config?: Record<string, unknown>;
  position?: [number, number] | null;
}

export interface LinkSpec { kind: LinkKind; src: string; dst: string; props?: Record<string, unknown> }

export interface Settings {
  mode?: "lockstep" | "wake";
  budget?: number;
  max_steps?: number;
  approvals?: "auto" | "manual" | "shadow";
  quarantine?: "self" | "team";
  blame?: "direct_teller" | "whole_route" | "first_hop";
  repair?: boolean;
  trace_provenance?: boolean;
  ticks?: number | null;
  extra?: { layout?: string; real?: boolean; [key: string]: unknown };
  [key: string]: unknown;
}

export interface TeamSpec {
  name: string;
  pack?: string;
  description?: string;
  settings?: Settings;
  nodes: NodeSpec[];
  links: LinkSpec[];
}

export interface Catalogue {
  nodes: { type: string; kind: NodeKind; description: string }[];
  tools: { name: string; description: string; outward: boolean; checking: boolean }[];
  graph_tools: string[];
  predicates: Record<string, string>;
  triggers: Record<TriggerKind, string>;
  links: Record<LinkKind, string>;
}

export interface Template { pack: string; name: string; title: string; description: string }

export interface PackInfo {
  name: string;
  title: string;
  options: { key: string; label: string; choices: { value: string; label: string }[] }[];
}

export interface RecordedRun {
  pack: string; path: string; name: string; options: Record<string, string>;
  checks_passed: number | null; checks_total: number | null;
}

export interface Summary {
  id: string;
  pack: "life" | "ringfire";
  name: string;
  title: string;
  model: string;
  tick: number;
  clock: string;
  running: boolean;
  finished: boolean;
  error: string;
  events: number;
  store: string;
}

export interface Change { tick: number; status: string; reason: string }

export interface BeliefView {
  id: string;
  subject: string;
  predicate: string;
  value: unknown;
  text: string;
  origin: "observed" | "told" | "derived";
  status: string;
  born: number;
  routes: string[][];
  sources: string[];
  history: Change[];
}

export interface Proposal {
  id: string;
  node: string;
  tool: string;
  arguments: Record<string, unknown>;
  basis: string[];
  tick: number;
  status: string;
  result: string;
  note: string;
}

export interface ExposureView { viewer: string; agent: string; tick: number; reason: string; changed: string[] }

export interface LiveNode {
  id: string;
  type: string;
  kind: NodeKind;
  label: string;
  role: string;
  pending: string[];
  distrusts: string[];
  last_turn: number | null;
}

export interface LifeWorld {
  lens: "life";
  events: { id: string; title: string; start: string; end: string; deleted: boolean }[];
  cabs: { id: string; pickup: string; to: string; cancelled: boolean }[];
  tasks: { id: string; title: string; due: string; done: boolean }[];
  subscriptions: Record<string, string>;
  payments: { tick: number; payee: string; amount: number; reference: string }[];
  sent: { id: string; tick: number; to: string; subject: string; body: string }[];
  mail: { id: string; tick: number; from: string; to: string; subject: string; feed: string; scam: boolean }[];
  departs: string;
}

export interface FireWorld {
  lens: "ringfire";
  n_agents: number;
  fields: { id: number; owner: number; state: string; ignitions: number[]; strength?: number }[];
  imposters: Record<string, string>;
  water_left: Record<string, number>;
  linear?: boolean; // fire strength moves by 1 a day, up to max_strength
  max_strength?: number;
}

export interface SpaceState extends Summary {
  team: TeamSpec;
  nodes: LiveNode[];
  outside: { id: string; quarantined_by: string[] }[];
  links: { src: string; dst: string }[];
  beliefs: Record<string, BeliefView[]>;
  proposals: Proposal[];
  exposures: ExposureView[];
  world: { lens?: string; [key: string]: unknown };
  clocks: string[];
  score: Record<string, unknown> & { checks?: Record<string, boolean> };
}

export interface RunEvent { seq: number; tick: number; kind: string; [key: string]: unknown }

export interface Why {
  viewer: string;
  belief: BeliefView;
  upstream: { observation: string; kind: string; sender: string | null; tick: number; route: string[] | null; item: string | null; source_belief: string | null }[];
  downstream: { node: string; belief: string; status: string }[];
  derived_from: { belief: string; status: string; text: string }[];
  dependents: { id: string; hops: number; status: string; text: string }[];
  cut_by_distrust: string[];
  changes: Change[];
  actions: { id: string; tool: string; status: string; arguments: Record<string, unknown> }[];
  cypher: Record<string, string>;
  live: Record<string, { rows: string[][]; ms: number }>;
  store: string;
}

// ---- your apps and your agents (src/graph_agent/service/connections.py, packs/apps/setup.py) ----

/** One line of connections.json: a preset with changes, or a server in full. */
export type ConnectionEntry = Record<string, unknown> & { preset?: string; name?: string };

export interface ConnectionInfo {
  name: string;
  label: string;
  about: string;
  secrets: string[];
  missing: string[]; // the secrets not set in .env yet
  feeds: string[];
  include: string[] | null;
  outward: Record<string, boolean>;
}

export interface Preset { name: string; label: string; about: string }

export interface ConnectionTest {
  ok: boolean;
  error?: string;
  tools?: { name: string; description: string; outward: boolean }[];
  feeds?: { name: string; items?: number; sample?: string[]; sign_in?: string; error?: string }[];
}

export interface AgentSetup {
  name: string;
  job: string;
  looks_after?: string[];
  apps?: string[];
  talks_to?: string[] | null;
  carries_out?: boolean;
  role?: string;
}

export interface AppsSetup {
  name: string;
  agents: AgentSetup[];
  things?: Record<string, string[]>;
  unowned?: string | null;
  approvals?: "auto" | "manual" | "shadow";
  polls?: number;
}

/** One of your teams (`team`: its id, its file's name; null: the example, not saved), and the list
 * of all of them. */
export interface SetupView {
  teams: { id: string; name: string }[];
  team: string | null;
  setup: AppsSetup;
  saved: boolean;
  kinds: Record<string, string[]>;
  problems: string[];
}

/** Who is signed in (hosted only; the local console has no sign-in). */
export interface Me {
  hosted: boolean;
  user: { email: string; name: string } | null;
}
