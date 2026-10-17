// Served by the Python service (python -m graph_agent.service), which also answers /api.
// In development, `npm run dev` proxies /api to a service already running on port 8765.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  build: { outDir: "dist", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
