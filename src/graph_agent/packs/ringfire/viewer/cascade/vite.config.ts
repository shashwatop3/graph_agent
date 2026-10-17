// The build is one self-contained HTML file (scripts and styles inlined), so a page written by
// graph_agent.packs.ringfire.benchmark.cascade opens by double-click with no server, like the S12 replay page.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: { outDir: "dist", emptyOutDir: true },
});
