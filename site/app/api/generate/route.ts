import { NextRequest, NextResponse } from "next/server";
import { dispatchGeneration, readQuota, writeQuota } from "../../../lib/github";
import { canGenerate, chargeReservation, recordDispatch, rollDay, type QuotaState } from "../../../lib/quota";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  const { appid } = (await req.json().catch(() => ({}))) as { appid?: number };
  if (!appid || !Number.isInteger(Number(appid))) {
    return NextResponse.json({ error: "appid required" }, { status: 400 });
  }
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";

  const state = rollDay((await readQuota()) as QuotaState);
  const check = canGenerate(state, ip);
  if (!check.allowed) {
    // guard 1: reserve spent (or the secondary IP guard) -> queue fallback.
    // Identical copy for both, per DESIGN.md: the distinction is ours.
    return NextResponse.json(
      { state: "queue_fallback", reason: check.reason, detail: check.detail },
      { status: 200 },
    );
  }

  // Reserve up front so a burst cannot oversubscribe between check and record.
  // The workflow writes the authoritative charge afterwards, so the ledger
  // self-corrects if a pre-check races (GitHub variables have no CAS).
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
