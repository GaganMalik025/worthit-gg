/**
 * Server-only GitHub access. The token never reaches the browser — every call
 * that needs it goes through an /api/* route, which is why the progress feed is
 * a proxy rather than the client polling GitHub directly.
 */

const API = "https://api.github.com";

function env() {
  const token = process.env.GH_DISPATCH_TOKEN;
  const repo = process.env.GH_REPO;
  if (!token || !repo) {
    throw new Error("GH_DISPATCH_TOKEN and GH_REPO must be set");
  }
  return { token, repo };
}

async function gh(path: string, init: RequestInit = {}) {
  const { token, repo } = env();
  const res = await fetch(`${API}/repos/${repo}${path}`, {
    ...init,
    headers: {
      accept: "application/vnd.github+json",
      authorization: `Bearer ${token}`,
      "x-github-api-version": "2022-11-28",
      ...(init.headers ?? {}),
    },
    cache: "no-store",
  });
  return res;
}

/** The quota ledger. A repository variable, not a committed file: writable from
 *  here, always fresh, and it does not trigger a redeploy on every request. */
export async function readQuota(): Promise<Record<string, unknown>> {
  const res = await gh("/actions/variables/LIVE_QUOTA");
  if (res.status === 404) return {};
  if (!res.ok) throw new Error(`quota read: ${res.status}`);
  const { value } = (await res.json()) as { value: string };
  try {
    return JSON.parse(value || "{}");
  } catch {
    return {};
  }
}

export async function writeQuota(state: Record<string, unknown>) {
  const body = JSON.stringify({ name: "LIVE_QUOTA", value: JSON.stringify(state) });
  const patch = await gh("/actions/variables/LIVE_QUOTA", { method: "PATCH", body });
  if (patch.ok || patch.status === 204) return;
  await gh("/actions/variables", { method: "POST", body });
}

export async function dispatchGeneration(appid: number, ip: string) {
  const res = await gh("/dispatches", {
    method: "POST",
    body: JSON.stringify({
      event_type: "generate-verdict",
      client_payload: { appid: String(appid), ip },
    }),
  });
  if (!res.ok && res.status !== 204) {
    throw new Error(`dispatch: ${res.status}`);
  }
}

/**
 * Does the verdict actually exist on the `verdicts` branch?
 *
 * GROUND TRUTH, and the reason it exists: the outcome variable is written by a
 * bookkeeping step that can fail (and did). When it failed, a verdict that had
 * genuinely generated and committed was invisible to the client, which sat on
 * "queued" until its 8-minute timeout and then told the user to request a page
 * that already existed.
 *
 * The artifact is the source of truth; the variable is only a hint that saves a
 * round trip. Anything that decides "published" asks this first.
 */
export async function verdictExists(
  appid: number | string,
): Promise<{ found: boolean; source?: string }> {
  // 1. main, as of the last build. Anything the nightly publish workflow has
  //    already squash-merged is prerendered and on disk - no API call needed,
  //    and a title stays "published" after the merge rather than reverting to
  //    "queued" because it left the verdicts branch view.
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    await fs.access(
      path.join(process.cwd(), `public/verdicts/${appid}.json`),
    );
    return { found: true, source: "main" };
  } catch {
    /* not merged yet - fall through to the branch */
  }

  // 2. the verdicts branch. Both layouts are checked: public/verdicts/ was the
  //    path until the Vercel Root Directory move, and verdicts generated before
  //    that move still sit there. Dropping the legacy path would strand them.
  for (const [dir, source] of [
    ["site/public/verdicts", "verdicts"],
    ["public/verdicts", "verdicts:legacy-path"],
  ]) {
    const res = await gh(`/contents/${dir}/${appid}.json?ref=verdicts`);
    if (res.ok) return { found: true, source };
  }
  return { found: false };
}

export interface RunInfo {
  id: number;
  status: string;
  created_at: string;
  appid: string | null;
}

/**
 * Statuses that mean a run is FINISHED. Everything else is treated as still
 * live - see listActiveRuns for why the list is inverted.
 *
 * From GitHub's workflow-runs API (docs fetched 2026-08-06), the full status
 * vocabulary is: completed, action_required, cancelled, failure, neutral,
 * skipped, stale, success, timed_out, in_progress, queued, requested, waiting,
 * pending. The non-terminal ones are queued, in_progress, requested, waiting,
 * pending and action_required.
 */
const TERMINAL_RUN_STATUS = new Set([
  "completed", "cancelled", "failure", "neutral",
  "skipped", "stale", "success", "timed_out",
]);

/**
 * Runs of the generate workflow that have not finished, oldest first.
 *
 * TWO THINGS CHANGED HERE, AND BOTH WERE CAUSING A STUCK UI.
 *
 * 1. It used to poll only `queued` and `in_progress`. GitHub also parks runs in
 *    `waiting`, `requested`, `pending` and `action_required` - a run awaiting a
 *    runner or an approval sits in one of those and was invisible, so
 *    /api/status saw zero active runs and told the user "You're next" forever.
 *
 * 2. The filter is now by EXCLUSION of terminal statuses, in a single
 *    unfiltered request, rather than one request per status. That is fewer API
 *    calls per poll, and it fails safe: a status GitHub adds later counts as
 *    active and stays visible, instead of silently vanishing from the queue the
 *    way `waiting` did.
 */
export async function listActiveRuns(): Promise<RunInfo[]> {
  const res = await gh(
    "/actions/workflows/generate-verdict.yml/runs?per_page=50",
  );
  if (!res.ok) return [];
  const { workflow_runs = [] } = (await res.json()) as {
    workflow_runs: { id: number; status: string; created_at: string }[];
  };
  return workflow_runs
    .filter((r) => !TERMINAL_RUN_STATUS.has(r.status))
    .map((r) => ({ ...r, appid: null }))
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/**
 * One workflow step -> one stage dot in the progress feed.
 *
 * `skipped` IS A TRUTHY CONCLUSION. The old expression was
 * `s.conclusion ? "failed" : ...`, so when a run died at ingest the four stages
 * that never ran came back as `skipped` and rendered as four more failures. A
 * single real failure showed the user five red stages and implied the whole
 * pipeline collapsed.
 *
 * Skipped means DID NOT RUN, which on this feed is `pending` - the same thing a
 * stage shows before its turn. It is not a success and it is certainly not a
 * failure, and only the step that actually failed should be marked as one.
 */
export function uiStatus(s: { status: string; conclusion: string | null }) {
  if (s.conclusion === "success") return "completed";
  if (s.conclusion === "skipped") return "pending";
  if (s.conclusion) return "failed";        // failure, cancelled, timed_out
  return s.status === "in_progress" ? "in_progress" : "pending";
}

/** Step names of a run's job, in order — the five UI stages. */
export async function runSteps(runId: number) {
  const res = await gh(`/actions/runs/${runId}/jobs`);
  if (!res.ok) return { status: "unknown", steps: [] as { key: string; status: string }[] };
  const { jobs = [] } = (await res.json()) as {
    jobs: {
      status: string;
      conclusion: string | null;
      steps?: { name: string; status: string; conclusion: string | null }[];
    }[];
  };
  const job = jobs[0];
  const UI = ["ingest", "filter", "extract", "verdict", "qr4"];
  const steps = (job?.steps ?? [])
    .filter((s) => UI.includes(s.name))
    .map((s) => ({
      key: s.name,
      status: uiStatus(s),
    }));
  return { status: job?.status ?? "unknown", steps };
}
