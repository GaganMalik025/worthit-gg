"use client";

/**
 * Fires `verdict_view`. Renders nothing.
 *
 * It is a separate component rather than a hook inside VerdictPage so that
 * VerdictPage's props, and therefore its contract tests, are untouched - and so
 * that the one thing this needs (WHICH loader answered) stays in page.tsx,
 * which is the only place that knows.
 *
 * `source` is the cache/live distinction PRD F7 asks for:
 *   "cache" - the prerendered static read from site/public/verdicts/
 *   "live"  - fetched at request time from the `verdicts` branch, i.e. a title
 *             generated on demand and not yet merged to main
 * It describes THE PATH THAT SERVED THIS REQUEST, not the title's history: a
 * live-generated verdict becomes "cache" once it merges and redeploys. That is
 * the right reading for a latency/experience metric and the wrong one for
 * "how many titles did live generation produce" - which is a pipeline
 * question, answered by the quota ledger, not by this event.
 *
 * The ref guard is load-bearing in development, where React runs effects twice
 * on mount; without it every local view double-counts.
 */

import { useEffect, useRef } from "react";
import { capture } from "../lib/analytics";

export function VerdictView({
  appid,
  verdictWord,
  source,
}: {
  appid: string;
  verdictWord: string;
  source: "cache" | "live";
}) {
  const fired = useRef(false);
  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    capture("verdict_view", { appid, verdict: verdictWord, source });
  }, [appid, verdictWord, source]);
  return null;
}
