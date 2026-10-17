// Copy the built page to src/graph_agent/packs/ringfire/viewer/cascade.html, the template the Python side fills with run data.
import { copyFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
copyFileSync(here("../dist/index.html"), here("../../cascade.html"));
console.log("wrote viewer/cascade.html (in the Ring Fire pack)");
