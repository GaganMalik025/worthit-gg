import { NextRequest, NextResponse } from "next/server";
import { isActive, listRuns, readQuota, runOutcome, runSteps, verdictExists } from "../../../lib/github";
import { dispatchLost, type QuotaState } from "../../../lib/quota";

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
  const exists = await verdictExists(appid);
  if (exists.found) {
    return NextResponse.json({ state: "published", source: exists.source });
  }

  // 2. the ledger - now ONLY for the dispatch timestamp.
  //
  //    This used to read quota.outcomes[appid] for terminal states. Nothing
  //    writes that field: the workflow step that was supposed to could not, and
  //    said nothing. Reading it was therefore always a no-op that looked like a
  //    fast path, so it is gone rather than left as decoration. Terminal state
  //    comes from the run itself in step 4.
  const quota = (await readQuota()) as QuotaState;

  // 3. this request's own run. One listing serves both questions below, so a
  //    poll still costs the same number of GitHub calls as before.
  const runs = await listRuns();
  const active = runs.filter(isActive);
  const mine = active.find((r) => r.appid === appid);

  if (mine) {
    // Stages come from MY run, not from whichever run happens to be oldest.
    // That assumption held only at a concurrency of one, and broke the instant
    // a second person was waiting: they were shown someone else's progress.
    const steps = await runSteps(mine.id);
    const started = steps.steps.some((s) => s.status !== "pending");
    const ahead = active.filter((r) => r.created_at < mine.created_at).length;
    if (started && ahead === 0) {
      return NextResponse.json({ state: "running", stages: steps.steps });
    }
    return NextResponse.json({ state: "queued", ahead });
  }

  // 4. no ACTIVE run for this appid - did one already finish?
  //    Derived from the run's own steps rather than from a ledger variable the
  //    runner cannot write. Newest first: a retry supersedes an earlier attempt.
  const finished = runs.filter((r) => r.appid === appid).at(-1);
  if (finished) {
    const outcome = await runOutcome(finished.id);
    if (outcome && outcome !== "published") {
      return NextResponse.json({ state: outcome, run_id: finished.id });
    }
    // "published" but step 1 found no artifact: the commit step is still
    // pushing, or the branch has not caught up. Keep polling - the artifact
    // stays the only thing allowed to declare success.
    return NextResponse.json({ state: "queued", ahead: 0 });
  }

  // 5. no artifact, no outcome, and no run for this appid in ANY state.
  //    This used to return {queued, ahead: 0} - the same response as a genuine
  //    "you're next", so a request whose run never existed polled until timeout
  //    showing a queue position it did not have.
  if (dispatchLost(quota, appid)) {
    return NextResponse.json({ state: "dispatch_lost", appid });
  }
  // inside the window: the run genuinely has not appeared yet
  return NextResponse.json({ state: "queued", ahead: 0 });
}
