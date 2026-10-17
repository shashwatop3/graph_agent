// The data the page plays back. These mirror the TypedDicts in
// src/graph_agent/harness/cascade.py, which writes it; change both together.

export interface DayView {
  day: number;
  ignited: number[]; // fields that caught fire
  burnt_out: number[];
  regrown: number[]; // burnt fields that grew back (the long game)
  saved: number[]; // fields the fire reached on a day they were watered
  watered: number[]; // agents who watered
  links_added: number[][];
}

export interface MessageView {
  day: number;
  sender: number;
  receiver: number;
  route: number[]; // every agent the claim passed through, the first one included
  field: number;
  claim_day: number;
  altered: boolean; // an imposter changed or invented the claim on its way
}

export interface ExposureView {
  day: number;
  viewer: number;
  distrusted: number;
  reason: string;
  changed: string[];
}

export interface StepView {
  tool: string;
  arguments: Record<string, unknown>;
  result: string;
  error: boolean;
}

export interface TurnView {
  final: string;
  steps: StepView[];
}

export interface CutView {
  day: number;
  agent: number;
  reason: string;
}

export interface BeliefView {
  id: string;
  field: number;
  value: number | string; // the arrival day; an agent can assert anything, such as "unknown"
  origin: "told" | "observed" | "derived" | string;
  status: string; // at the end of the game
  born: number;
  history: [number, string][]; // [day, new status] for every change an exposure made
  routes: number[][]; // supporting routes; [] is a direct observation
  sources: string[]; // DERIVED_FROM
  dependents: string[];
  cuts: CutView[];
  sent: { day: number; to: number }[];
  became: { agent: number; id: string }[];
  true: boolean | null;
}

export interface RunView {
  system: string;
  model: string;
  days: DayView[];
  messages: MessageView[];
  exposures: ExposureView[];
  turns: Record<string, TurnView>; // "agent|day"
  beliefs: Record<string, BeliefView[]>; // agent number -> beliefs; {} with no belief store
  score: Record<string, unknown>;
}

export interface ScenarioView {
  seed: number;
  n_agents: number;
  fields_per_agent: number;
  n_fields: number;
  imposters: Record<string, string>; // agent number -> behaviour
  start_links: number[][];
}

export interface CascadeData {
  scenario: ScenarioView;
  runs: Record<string, RunView>; // label -> run
}
