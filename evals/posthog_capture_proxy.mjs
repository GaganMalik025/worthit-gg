/**
 * A pass-through proxy that records exactly what the browser sends to PostHog.
 *
 * Why this exists: the browser tooling shows the CORS preflight but not the
 * POST body, and posthog-js resolves its transport and binds its logger at
 * init - before any patch injected from outside can reach either. So the only
 * way to read the real payload of a real click is to sit in the path.
 *
 * It FORWARDS to the real ingestion host and returns the real upstream status,
 * so a run through this proxy is still an end-to-end run: same payload, same
 * endpoint, same answer from PostHog. It is a verification tool, never
 * something the app points at outside a verification run.
 *
 *   node evals/posthog_capture_proxy.mjs <log-file> [port]
 *   # then, temporarily, in site/.env.local:
 *   #   NEXT_PUBLIC_POSTHOG_HOST=http://localhost:3111
 *   # and restart `npm run dev`. PUT THE REAL HOST BACK AFTERWARDS.
 *
 * The project key is echoed by the client in every payload. This script
 * redacts it before writing, so the log is safe to commit as evidence.
 */

import { createServer } from "node:http";
import { appendFileSync } from "node:fs";

const LOG = process.argv[2];
const PORT = Number(process.argv[3] ?? 3111);
const UPSTREAM = "https://us.i.posthog.com";

if (!LOG) {
  console.error("usage: node evals/posthog_capture_proxy.mjs <log-file> [port]");
  process.exit(2);
}

const redact = (s) =>
  String(s)
    .replace(/ph[xcs]_[A-Za-z0-9]{20,}/g, "ph?_<REDACTED>")
    .replace(/"(distinct_id|\$device_id)":"[^"]*"/g, '"$1":"<id>"');

/** posthog posts raw JSON, `data=<urlencoded json>`, or - when the URL carries
 *  `compression=base64` - a base64 body. All three appear in one page load, and
 *  the interesting events tend to arrive on the third. */
function decodePayload(raw, url = "") {
  let s = raw;
  const m = /^data=(.*)$/s.exec(s);
  if (m) s = decodeURIComponent(m[1].replace(/\+/g, " "));
  if (url.includes("compression=base64")) {
    try { s = Buffer.from(s, "base64").toString("utf-8"); } catch { /* not base64 after all */ }
  }
  try {
    const j = JSON.parse(s);
    const arr = Array.isArray(j) ? j : j.batch || [j];
    return arr.map((e) => ({ event: e.event, properties: e.properties }));
  } catch {
    return null;
  }
}

/** Only the properties we deliberately attach, plus the two PostHog-owned ones
 *  that matter for reading the result. The rest is autocapture context and
 *  would bury the thing being checked. */
const KEEP = new Set([
  "appid", "verdict", "source", "query_length",
  "$current_url", "$internal_or_test_user",
]);

createServer((req, res) => {
  const chunks = [];
  req.on("data", (c) => chunks.push(c));
  req.on("end", async () => {
    const body = Buffer.concat(chunks).toString("utf-8");
    const events = decodePayload(body, req.url);
    const stamp = new Date().toISOString();

    let upstream = "not forwarded";
    let upstreamBody = "";
    try {
      const r = await fetch(UPSTREAM + req.url, {
        method: req.method,
        headers: { "content-type": req.headers["content-type"] ?? "application/json" },
        body: req.method === "GET" || req.method === "HEAD" ? undefined : body,
      });
      upstream = r.status;
      upstreamBody = (await r.text()).slice(0, 300);
    } catch (e) {
      upstream = "PROXY ERROR: " + e.message;
    }

    // redact() must cover the URL too - posthog puts the project key in the
    // path on /array/<key>/config.js, not only in the body.
    const lines = [`[${stamp}] ${req.method} ${redact(req.url)} -> upstream ${upstream} ${redact(upstreamBody)}`];
    if (events) {
      for (const e of events) {
        const props = Object.fromEntries(
          Object.entries(e.properties ?? {}).filter(([k]) => KEEP.has(k)),
        );
        lines.push(`    event=${e.event}  props=${redact(JSON.stringify(props))}`);
      }
    } else if (req.method !== "OPTIONS" && body) {
      lines.push(`    <unparsed body, ${body.length} bytes>`);
    }
    const text = lines.join("\n") + "\n";
    appendFileSync(LOG, text);
    process.stdout.write(text);

    res.writeHead(typeof upstream === "number" ? upstream : 502, {
      "access-control-allow-origin": req.headers.origin ?? "*",
      "access-control-allow-headers": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "content-type": "application/json",
    });
    res.end(upstreamBody || "{}");
  });
}).listen(PORT, () => console.log(`posthog capture proxy on :${PORT} -> ${UPSTREAM}, logging to ${LOG}`));
