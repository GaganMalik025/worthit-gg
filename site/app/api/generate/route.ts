import { NextRequest, NextResponse } from "next/server";
import { admit, hashClient, inSearchIndex } from "../../../lib/admission";
import {
  dispatchGeneration,
  fetchVerdictCost,
  listRunsStrict,
  readQuota,
  runOutcome,
  verdictExists,
  writeQuota,
} from "../../../lib/github";
import { isAppid } from "../../../lib/verdict";

export const dynamic = "force-dynamic";

/** Every decision and its reasoning lives in lib/admission.ts, where it is tested. */
export async function POST(req: NextRequest) {
  const { appid } = (await req.json().catch(() => ({}))) as { appid?: unknown };
  if (!isAppid(appid)) {
    return NextResponse.json({ error: "appid required" }, { status: 400 });
  }
  const origin = req.nextUrl.origin;
  const ip =
    req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() ?? "unknown";

  const { status, body } = await admit(String(appid), hashClient(ip), {
    inSearchIndex: (id) => inSearchIndex(id, origin),
    verdictExists: (id) => verdictExists(id, origin),
    readQuota,
    writeQuota,
    listRuns: listRunsStrict,
    runOutcome,
    fetchVerdictCost,
    dispatch: dispatchGeneration,
  });
  return NextResponse.json(body, { status });
}
