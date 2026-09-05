/**
 * Copy the pdf.js worker that react-pdf actually resolves into public/.
 *
 * react-pdf pins its own pdfjs-dist, and the worker must match the API version
 * exactly or the viewer refuses to open a file. Copying it on install means the
 * two cannot drift apart when either package is upgraded.
 */
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..");
const require = createRequire(join(webRoot, "node_modules", "react-pdf", "package.json"));

let pdfjsRoot;
try {
  pdfjsRoot = dirname(require.resolve("pdfjs-dist/package.json"));
} catch {
  console.warn("[pdf-worker] react-pdf is not installed yet; skipping.");
  process.exit(0);
}

const source = join(pdfjsRoot, "build", "pdf.worker.min.mjs");
if (!existsSync(source)) {
  console.warn(`[pdf-worker] worker not found at ${source}; skipping.`);
  process.exit(0);
}

mkdirSync(join(webRoot, "public"), { recursive: true });
copyFileSync(source, join(webRoot, "public", "pdf.worker.min.mjs"));

const { version } = require("pdfjs-dist/package.json");
console.log(`[pdf-worker] public/pdf.worker.min.mjs now matches pdfjs-dist ${version}`);
