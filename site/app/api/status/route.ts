import { NextRequest, NextResponse } from "next/server";
import { listActiveRuns, readQuota, runSteps, verdictExists } from "../../../lib/github";
import type { QuotaState } from "../../../lib/quota";

export const dynamic = "force-dynamic";

/**
 * Three shapes the client renders:
 *   {state:"queued",   ahead:N}
 *   {state:"running",  stages:[...]}
 *   {state:"published"|"qr4_failed"|"stage_failed"}
 *
 * Queue position is a fact we can state. A queue TIME estimate would be a guess
 * multiplied by an unknown queue, so it is never returned - the measured
 * duration copy belongs to the running state only.
 *
 * ORDER MATTERS. The artifact is checked BEFORE the bookkeeping variable,
 * because the variable is written by a step that can fail. It did fail once,
 * and the result was a verdict that existed, was committed, and was live via
 * the proxy - while the client polled "queued" until it timed out and told the
 * user to request the page it was already serving. Deciding "published" from
 * the artifact makes that failure mode impossible rather than unlikely.
 */
export async function GET(req: NextRequest) {
  const appid = req.nextUrl.searchParams.get("appid");
  if (!appid) return NextResponse.json({ error: "appid required" }, { status: 400 });

  // 1. ground truth: is it actually there?
  if (await verdictExists(appid)) {
    return NextResponse.json({ state: "published", source: "artifact" });
  }

  // 2. the ledger, for terminal states that leave no artifact by design
  //    (qr4_failed deletes it; stage_failed never wrote one)
  const quota = (await readQuota()) as QuotaState;
  const outcome = quota.outcomes?.[appid];
  if (outcome && outcome.state !== "published") {
    return NextResponse.json({ state: outcome.state, at: outcome.at });
  }
  // A "published" ledger entry with no artifact means the commit was reverted
  // or the branch rewritten - trust the artifact and keep polling.

  // 3. still working
  const runs = await listActiveRuns();
  if (runs.length === 0) {
    return NextResponse.json({ state: "queued", ahead: 0 });
  }

  // The oldest active run is the one executing (concurrency group of 1).
  const running = runs[0];
  const steps = await runSteps(running.id);
  const started = steps.steps.some((s) => s.status !== "pending");
  const ahead = Math.max(0, runs.length - 1);

  if (started && runs.length === 1) {
    return NextResponse.json({ state: "running", stages: steps.steps });
  }
  return NextResponse.json({ state: "queued", ahead });
}
