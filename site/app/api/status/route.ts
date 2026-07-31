import { NextRequest, NextResponse } from "next/server";
import { listActiveRuns, readQuota, runSteps } from "../../../lib/github";
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
 */
export async function GET(req: NextRequest) {
  const appid = req.nextUrl.searchParams.get("appid");
  if (!appid) return NextResponse.json({ error: "appid required" }, { status: 400 });

  const quota = (await readQuota()) as QuotaState;
  const outcome = quota.outcomes?.[appid];
  if (outcome) {
    return NextResponse.json({ state: outcome.state, at: outcome.at });
  }

  const runs = await listActiveRuns();
  if (runs.length === 0) {
    return NextResponse.json({ state: "queued", ahead: 0 });
  }

  // The oldest active run is the one executing (concurrency group of 1).
  const running = runs[0];
  const steps = await runSteps(running.id);
  const started = steps.steps.some((s) => s.status !== "pending");

  // We cannot label runs by appid from the runs API, so position is derived
  // from queue depth: everything active that is not the head is waiting.
  const ahead = Math.max(0, runs.length - 1);

  if (started && runs.length === 1) {
    return NextResponse.json({ state: "running", stages: steps.steps });
  }
  return NextResponse.json({ state: "queued", ahead });
}
