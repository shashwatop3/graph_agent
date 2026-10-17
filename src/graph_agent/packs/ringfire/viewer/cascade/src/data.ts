// The run data is embedded in the page by the Python side (graph_agent.harness.cascade). In
// `npm run dev` the placeholder is still there, so the page loads public/sample.json instead.

import type { CascadeData } from "./types";

const PLACEHOLDER = "__CASCADE_DATA__";

export async function loadData(): Promise<CascadeData> {
  const text = document.getElementById("cascade-data")?.textContent?.trim() ?? "";
  if (text && text !== PLACEHOLDER) return JSON.parse(text) as CascadeData;
  const response = await fetch("sample.json");
  if (!response.ok)
    throw new Error("No run data in this page, and no sample.json next to it (see viewer/cascade/README.md).");
  return (await response.json()) as CascadeData;
}
