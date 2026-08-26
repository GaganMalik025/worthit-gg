"use client";

/**
 * What the user watches while a verdict is generated.
 *
 * Three states, in order: queued behind other runs → running the five stages →
 * terminal. The wave backdrop keeps moving underneath all of them; this panel
 * is transparent and sits above it, so "something is happening" is carried by
 * the page itself even before the user's own job starts.
 *
 * Copy rules (DESIGN.md): active voice, sentence case, no exclamation marks,
 * personality from precision rather than jokes. Counts set in mono, because a
 * count is evidence.
 *
 * NO TIME ESTIMATE WHILE QUEUED, and the queued panel's third line is not one.
 * Position is a fact; "about six minutes" would be a guess multiplied by an
 * unknown queue, so the WAIT stays unstated. "Once yours starts, it takes a few
 * minutes" says nothing about the queue - it describes the GENERATION, the
 * thing that begins when the wait ends, so a queued user knows what they are
 * waiting for. Queue length x duration is still never multiplied out, which is
 * the guess the rule above exists to prevent.
 *
 * THE DURATION IS UNMEASURED FOR THE LIVE PATH. This comment used to call it
 * "the measured duration"; that was wrong and is corrected here. Nothing in the
 * repo has timed an end-to-end live dispatch - generate_one.py does compute
 * `total_seconds` per run, but it reaches only the run payload and the log,
 * never a committed artifact. The only committed timing evidence is BATCH:
 * published titles at 26-121s, median 76s (evals/batch-2026-08-24.txt) and
 * 68-252s, median 114s (evals/batch-2026-08-21.txt). Batch is not live - it
 * pushes many titles through one shared pacer, while a live run is a single
 * always-flash-lite job that also waits on the in-pipeline QR-4 gate before
 * anything renders. "A few minutes" is consistent with that range and is NOT a
 * measurement of the thing it describes.
 *
 * So this is deliberately the SAME sentence fragment the running state uses,
 * not a second differently-worded guess: one claim, stated in two places, with
 * one place to correct it. CLAUDE.md's live-generation guard 3 - "if a measured
 * run gets slower, the copy changes, not the claim" - needs a measured run
 * first. BACKLOG 2026-08-26.
 */

import { useEffect, useRef, useState } from "react";

const STAGES = [
  { key: "ingest", label: "Reading Steam reviews" },
  { key: "filter", label: "Filtering out junk and unsafe reviews" },
  { key: "extract", label: "Reading each playtime cohort" },
  { key: "verdict", label: "Writing the verdict" },
  { key: "qr4", label: "Safety check" },
];

type Status =
  | { state: "queued"; ahead: number }
  | { state: "running"; stages: { key: string; status: string }[] }
  | { state: "published" }
  | { state: "qr4_failed" }
  | { state: "stage_failed" }
  /* dispatched, but GitHub never produced a run. Terminal: the wait is not
     going to end on its own, so fall back rather than keep polling. */
  | { state: "dispatch_lost" }
  | { state: "queue_fallback"; reason?: string };

const HARD_TIMEOUT_MS = 8 * 60 * 1000;

export function GenerationProgress({
  appid,
  gameName,
  onPublished,
  onFallback,
}: {
  appid: number;
  gameName: string;
  onPublished: () => void;
  onFallback: () => void;
}) {
  const [status, setStatus] = useState<Status>({ state: "queued", ahead: 0 });
  const started = useRef(Date.now());

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      // a workflow that dies without writing an outcome must still terminate
      // the UI rather than leave the user polling forever
      if (Date.now() - started.current > HARD_TIMEOUT_MS) return onFallback();
      try {
        const res = await fetch(`/api/status?appid=${appid}`);
        const next = (await res.json()) as Status;
        if (!alive) return;
        setStatus(next);
        if (next.state === "published") return onPublished();
        if (
          next.state === "qr4_failed" ||
          next.state === "stage_failed" ||
          next.state === "dispatch_lost"
        ) {
          return onFallback();
        }
      } catch {
        /* transient; the next tick retries */
      }
      setTimeout(tick, 2000);
    };
    tick();
    return () => {
      alive = false;
    };
  }, [appid, onPublished, onFallback]);

  if (status.state === "queued") {
    const { ahead } = status;
    return (
      <div className="gen-panel">
        <h2 className="display">
          {ahead === 0 ? "You're next." : <><span className="mono">{ahead}</span> ahead of you.</>}
        </h2>
        <p className="sub">
          We generate one verdict at a time, so each one gets the full quota.
        </p>
        <p className="sub">
          Holding your place for <strong>{gameName}</strong>.
        </p>
        <p className="sub">
          Once yours starts, it takes a few minutes.
        </p>
      </div>
    );
  }

  if (status.state === "running") {
    const byKey = new Map(status.stages.map((s) => [s.key, s.status]));
    return (
      <div className="gen-panel">
        <h2 className="display">Reading the reviews for {gameName}.</h2>
        <p className="sub">This takes a few minutes.</p>
        <ol className="stages">
          {STAGES.map((s) => {
            const st = byKey.get(s.key) ?? "pending";
            return (
              <li key={s.key} className={`stage ${st}`}>
                <span className="mark" aria-hidden="true">
                  {st === "completed" ? "✓" : st === "in_progress" ? "▸" : "·"}
                </span>
                <span className="label">{s.label}</span>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  return null;
}

/** Shown for BOTH reserve exhaustion and QR-4 failure — identical copy, because
 *  the distinction is ours, not the buyer's (DESIGN.md). */
export function QueueFallback({ gameName }: { gameName: string }) {
  const [sent, setSent] = useState(false);
  return (
    <div className="gen-panel">
      <h2 className="display">Not in the catalog yet.</h2>
      <p className="sub">
        Request it and it&rsquo;ll be here within 48 hours.
      </p>
      {sent ? (
        <p className="sub">Queued. Check back tomorrow.</p>
      ) : (
        <button
          className="cta"
          onClick={() => {
            setSent(true);
            // PostHog request_submit fires here (3.3)
          }}
        >
          Request verdict
        </button>
      )}
      <p className="sub mono">{gameName}</p>
    </div>
  );
}
