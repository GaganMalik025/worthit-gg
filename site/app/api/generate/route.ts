import { NextRequest, NextResponse } from "next/server";
import {
  dispatchGeneration,
  fetchVerdictCost,
  listRuns,
  readQuota,
  runOutcome,
  sweepReconciliations,
  writeQuota,
} from "../../../lib/github";
import { canGenerate, chargeReservation, recordDispatch, rollDay, type QuotaState } from "../../../lib/quota";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { appid } = (await req.json().catch(() => ({}))) as { appid?: number };
  if (!appid || !Number.isInteger(Number(appid))) {
    return NextResponse.json({ error: "appid required" }, { status: 400 });
  }
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";

  const read = rollDay((await readQuota()) as QuotaState);

  // Give back what today's FINISHED generations did not spend, before deciding
  // whether this one fits. Deliberately placed between the read and the charge:
  // the correction then rides the write this route already performs, so it adds
  // no writer to a ledger that has no compare-and-swap, and the fact and the
  // counter land in one PATCH.
  //
  // NEVER BLOCKS A DISPATCH. A sweep failure falls back to the un-reconciled
  // (higher) figure, which can only ever deny a request that the true number
  // would have allowed. Refusing to generate is recoverable; authorising
  // against budget that is already spent is not.
  const state = await sweepReconciliations(read, {
    listRuns,
    runOutcome,
    fetchVerdictCost,
  }).catch(() => read);

  const check = canGenerate(state, ip);
  if (!check.allowed) {
    // guard 1: reserve spent (or the secondary IP guard) -> queue fallback.
    // Identical copy for both, per DESIGN.md: the distinction is ours.
    return NextResponse.json(
      { state: "queue_fallback", reason: check.reason, detail: check.detail },
      { status: 200 },
    );
  }

  // Reserve up front, in full, so a burst cannot oversubscribe between check
  // and record.
  //
  // This used to say the workflow wrote the authoritative charge afterwards and
  // the ledger self-corrected. It never did: the runner's GITHUB_TOKEN cannot
  // write repository variables, so that step reported success while writing
  // nothing, and it has since been deleted outright (generate-verdict.yml,
  // "THIS STEP NO LONGER RECORDS ANYTHING"). Reservations simply stood at
  // EST_COST for the rest of the quota day. The correction is the sweep above
  // instead - site-side, from the cost the runner commits into the artifact.
  //
  // GitHub variables still have no CAS, and two concurrent dispatches can still
  // lose one another's charge. That race is untouched here.
  //
  // Record WHEN we asked, not just that we charged. /api/status needs it to
  // tell "the run has not appeared yet" from "the run is never coming" - those
  // were indistinguishable, and the second one rendered as "You're next"
  // forever.
  const charged = recordDispatch(chargeReservation(state, ip) as QuotaState, appid);
  await writeQuota(charged as Record<string, unknown>);
  // The ledger travels WITH the dispatch - the runner cannot read it itself.
  await dispatchGeneration(Number(appid), ip, charged as Record<string, unknown>);

  return NextResponse.json({ state: "dispatched", appid: Number(appid) });
}
