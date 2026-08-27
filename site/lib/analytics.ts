/**
 * The ONLY place the app touches posthog-js.
 *
 * Two reasons it exists rather than importing `posthog` at each call site:
 *
 *   1. The contract tests render VerdictPage under vitest's `node` environment
 *      (vitest.config.ts), so a browser SDK is evaluated on a path that has no
 *      `window`. One guarded seam is easier to keep honest than four.
 *   2. It gives citation-expand.contract.test.tsx exactly one thing to assert
 *      against.
 *
 * FAIL SILENT, ALWAYS. No key, no window, or a capture that throws must never
 * be able to break a verdict page. Analytics is the least important thing on
 * the screen and must behave like it.
 *
 * WHAT MAY BE PASSED IN `properties`: appid, verdict word, cache/live source,
 * a query LENGTH. Never review text, never the text a user typed, never an
 * email, never anything identifying. See BACKLOG 2026-08-26.
 */

import posthog from "posthog-js";

export function capture(event: string, properties: Record<string, unknown>): void {
  if (typeof window === "undefined") return;
  // Same literal-member-access form as instrumentation-client.ts, and the same
  // condition: if init did not run, capture must not either.
  if (!process.env.NEXT_PUBLIC_POSTHOG_KEY) return;
  try {
    posthog.capture(event, properties);
  } catch {
    /* analytics never breaks a page */
  }
}
