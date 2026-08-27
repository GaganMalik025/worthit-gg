/**
 * Render every committed verdict through VerdictPage and dump the HTML.
 *
 * Why this exists: 3.3 lifted the citation <details> out of VerdictPage into a
 * client component (components/Receipts.tsx) so it could carry the
 * `citation_expand` event. Invariant 9 says review text may appear ONLY behind
 * a citation expand, and the claim being made was that the lifted markup is a
 * verbatim copy. "Verbatim" is checkable, so it gets checked rather than
 * asserted in a comment: run this before the swap and after it, diff the two
 * dumps, and the claim is either true across all 539 verdicts or it is not.
 *
 * This is a MEASUREMENT DRIVER, not a test - it makes no assertions and the
 * suite does not run it. The artifact it produces is the evidence.
 *
 *   cd site && node ../evals/render_verdict_markup.mjs <out-file>
 *
 * Must be run from site/ so react/react-dom resolve from site/node_modules.
 */

import { readdir, readFile, writeFile, rm } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { pathToFileURL } from "node:url";

// This file lives in evals/ but its dependencies live in site/node_modules, so
// resolution is anchored to the working directory rather than to this file.
const { build } = createRequire(path.join(process.cwd(), "package.json"))("esbuild");

const OUT = process.argv[2];
if (!OUT) {
  console.error("usage: node ../evals/render_verdict_markup.mjs <out-file>");
  process.exit(2);
}

const SITE = process.cwd();
const VERDICTS = path.join(SITE, "public/verdicts");
const BUNDLE = path.join(SITE, ".render-markup.bundle.mjs");

const ENTRY = `
import { renderToStaticMarkup } from "react-dom/server";
import { VerdictPage } from "./components/VerdictPage";
import { normalizeVerdict } from "./lib/verdict";
export function render(raw) {
  return renderToStaticMarkup(VerdictPage({ verdict: normalizeVerdict(raw) }));
}
`;

await build({
  stdin: { contents: ENTRY, resolveDir: SITE, sourcefile: "entry.tsx", loader: "tsx" },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  // resolved from site/node_modules at import time, not inlined
  external: ["react", "react-dom", "react/*", "react-dom/*", "posthog-js"],
  outfile: BUNDLE,
  logLevel: "warning",
});

const { render } = await import(pathToFileURL(BUNDLE).href);

const files = (await readdir(VERDICTS)).filter((f) => f.endsWith(".json")).sort();
const out = [];
let failed = 0;
for (const f of files) {
  const raw = JSON.parse(await readFile(path.join(VERDICTS, f), "utf-8"));
  try {
    out.push(`===== ${f} =====\n${render(raw)}`);
  } catch (e) {
    failed++;
    out.push(`===== ${f} ===== RENDER FAILED: ${e.message}`);
  }
}

await writeFile(OUT, out.join("\n"), "utf-8");
await rm(BUNDLE, { force: true });
console.log(`rendered ${files.length} verdicts -> ${OUT} (${failed} render failures)`);
