import type { AppsSetup, Catalogue, ConnectionEntry, ConnectionInfo, ConnectionTest, Keys, Me, PackInfo, Preset, PublicStream, RecordedRun, RunEvent, SetupView, SpaceState, StreamEntry, StreamPeek, Summary, TeamSpec, Template, Why } from "./types";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}

const post = <T,>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

/** What a run is started with: the model and store, and the pack's own options (by key). */
export interface RunOptions {
  model: string;
  store: string;
  options: Record<string, string>;
}

export const api = {
  me: () => call<Me>("/api/me"),
  logout: () => fetch("/auth/logout", { method: "POST" }),
  packs: () => call<PackInfo[]>("/api/packs"),
  catalogue: (pack: string) => call<Catalogue>(`/api/catalogue?pack=${encodeURIComponent(pack)}`),
  templates: () => call<Template[]>("/api/templates"),
  template: (pack: string, name: string) => call<TeamSpec>(`/api/templates/${pack}/${name}`),
  validate: (team: TeamSpec) => post<{ ok: boolean; errors: string[] }>("/api/validate", team),
  spaces: () => call<Summary[]>("/api/spaces"),
  create: (pack: string, team: TeamSpec, name: string, options: RunOptions) =>
    post<Summary>("/api/spaces", { pack, team, name, ...options }),
  state: (id: string) => call<SpaceState>(`/api/spaces/${id}`),
  step: (id: string) => post<Summary>(`/api/spaces/${id}/step`),
  play: (id: string, delay = 0.3) => post<Summary>(`/api/spaces/${id}/play?delay=${delay}`),
  pause: (id: string) => post<Summary>(`/api/spaces/${id}/pause`),
  events: (id: string, since = 0) => call<RunEvent[]>(`/api/spaces/${id}/events?since=${since}`),
  why: (id: string, node: string, belief: string) =>
    call<Why>(`/api/spaces/${id}/why/${encodeURIComponent(node)}/${encodeURIComponent(belief)}`),
  runs: () => call<RecordedRun[]>("/api/runs"),
  replay: (run: RecordedRun) => post<Summary>("/api/runs/replay", { pack: run.pack, name: run.name, options: run.options }),
  decide: (id: string, proposal: string, approved: boolean) =>
    post<{ result: string }>(`/api/spaces/${id}/approvals/${proposal}`, { approved }),
  // your apps and your agents
  connections: () => call<{ presets: Preset[]; entries: ConnectionEntry[]; connections: ConnectionInfo[] }>("/api/connections"),
  saveConnections: (entries: ConnectionEntry[]) =>
    call<{ connections: ConnectionInfo[] }>("/api/connections", { method: "PUT", body: JSON.stringify({ connections: entries }) }),
  testConnection: (entry: ConnectionEntry) => post<ConnectionTest>("/api/connections/test", entry),
  setup: (pack: string, team?: string | null) => call<SetupView>(`/api/packs/${pack}/setup${teamQuery(team)}`),
  // no team: saved as a new one (the answer names it)
  saveSetup: (pack: string, setup: AppsSetup, team?: string | null) =>
    call<{ problems: string[]; team: string }>(`/api/packs/${pack}/setup${teamQuery(team)}`, { method: "PUT", body: JSON.stringify(setup) }),
  deleteSetup: (pack: string, team: string) =>
    call<{ deleted: string }>(`/api/packs/${pack}/setup${teamQuery(team)}`, { method: "DELETE" }),
  // hosted: your own keys (names only come back, never a value)
  keys: () => call<Keys>("/api/keys"),
  disconnectGoogle: () => post<{ google: boolean }>("/api/google/disconnect"),
  deleteMe: () => call<{ deleted: string }>("/api/me", { method: "DELETE" }),
  saveKey: (name: string, value: string) =>
    call<{ saved: string[] }>(`/api/keys/${encodeURIComponent(name)}`, { method: "PUT", body: JSON.stringify({ value }) }),
  deleteKey: (name: string) => call<{ saved: string[] }>(`/api/keys/${encodeURIComponent(name)}`, { method: "DELETE" }),
  checkSetup: (pack: string, setup: AppsSetup) => post<{ problems: string[] }>(`/api/packs/${pack}/setup/check`, setup),
  // live public data a team can read
  streams: () => call<{ topics: { topic: string; streams: PublicStream[] }[] }>("/api/streams"),
  peekStream: (entry: StreamEntry) => post<StreamPeek>("/api/streams/peek", entry),
};

function teamQuery(team?: string | null): string {
  return team ? `?team=${encodeURIComponent(team)}` : "";
}

/** Follow a space's event log live. Returns a function that stops listening. */
export function follow(id: string, since: number, onEvent: (event: RunEvent) => void): () => void {
  const source = new EventSource(`/api/spaces/${id}/stream?since=${since}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data as string) as RunEvent);
  return () => source.close();
}
