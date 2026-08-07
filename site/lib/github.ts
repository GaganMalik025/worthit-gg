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

/**
 * Fire the generation run, CARRYING TODAY'S LEDGER WITH IT.
 *
 * The workflow used to fetch the shared ledger itself, with `gh api
 * .../variables/LIVE_QUOTA`. It cannot: the runner's GITHUB_TOKEN can neither
 * read nor write repository variables (verified on run #5 - the read fails, and
 * an earlier write reported success while writing nothing). So the runner was
 * either silently falling back to the stale committed file, or - once that
 * fallback was removed - failing outright.
 *
 * We already hold the real ledger here, one line before dispatching, read with
 * the token that does have access. Sending the counters in the payload gives
 * the runner today's true numbers with no second credential and no second
 * source of truth. Counters only: `outcomes` and `by_ip_hour` are not the
 * runner's business and would bloat the payload.
 */
export async function dispatchGeneration(
  appid: number,
  ip: string,
  quota: Record<string, unknown> = {},
) {
  const COUNTERS = [
    "date", "live_used", "batch_used", "flash_used",
    "generations", "batch_generations", "flash_generations",
  ];
  const snapshot = Object.fromEntries(
    COUNTERS.filter((k) => k in quota).map((k) => [k, quota[k]]),
  );
  const res = await gh("/dispatches", {
    method: "POST",
    body: JSON.stringify({
      event_type: "generate-verdict",
      client_payload: { appid: String(appid), ip, quota: snapshot },
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
  conclusion: string | null;
  created_at: string;
  appid: string | null;
}

/**
 * The appid a run was dispatched for, read from its run-name.
 *
 * repository_dispatch does not surface client_payload on the runs API, so the
 * workflow puts the appid in `run-name:` and this reads it back out. Anything
 * unparseable (runs created before that existed) returns null and simply never
 * matches, which degrades to the old behaviour rather than mis-attributing.
 */
export function runAppid(r: { name?: string; display_title?: string }): string | null {
  return /verdict\s+(\d+)/.exec(r.display_title || r.name || "")?.[1] ?? null;
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
export async function listRuns(): Promise<RunInfo[]> {
  const res = await gh(
    "/actions/workflows/generate-verdict.yml/runs?per_page=50",
  );
  if (!res.ok) return [];
  const { workflow_runs = [] } = (await res.json()) as {
    workflow_runs: {
      id: number; status: string; conclusion: string | null;
      created_at: string; name?: string; display_title?: string;
    }[];
  };
  return workflow_runs
    .map((r) => ({
      id: r.id, status: r.status, conclusion: r.conclusion,
      created_at: r.created_at, appid: runAppid(r),
    }))
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export const isActive = (r: RunInfo) => !TERMINAL_RUN_STATUS.has(r.status);

export async function listActiveRuns(): Promise<RunInfo[]> {
  return (await listRuns()).filter(isActive);
}

/**
 * The terminal state of a FINISHED run, read from the run itself.
 *
 * This replaces trusting `outcomes` in the LIVE_QUOTA variable. That variable
 * is written by a bookkeeping step inside the workflow, and the runner's
 * GITHUB_TOKEN cannot write repository variables - so the step reported success
 * (it is `continue-on-error`) while writing nothing. A run that had genuinely
 * failed left no record at all, and /api/status fell through to the lost-
 * dispatch branch and told the user their request was never received.
 *
 * The run's own steps cannot silently fail to record: they ARE the record.
 * Deriving from them needs no extra credential, and it cannot go stale.
 */
export type Outcome = "published" | "qr4_failed" | "stage_failed" | null;

/** The decision itself, separated from the fetch so it can be tested directly. */
export function deriveOutcome(
  status: string,
  conclusion: string | null,
  steps: { key: string; status: string }[],
): Outcome {
  if (status !== "completed") return null;        // still going; not terminal
  if (conclusion === "success") return "published";
  // invariant 8 gets its own state: a QR-4 rejection is a content decision, not
  // a crash, and the UI says something different about it.
  if (steps.find((s) => s.key === "qr4")?.status === "failed") return "qr4_failed";
  return "stage_failed";
}

export async function runOutcome(runId: number): Promise<Outcome> {
  const { status, conclusion, steps } = await runSteps(runId);
  return deriveOutcome(status, conclusion, steps);
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
  if (!res.ok) {
    return {
      status: "unknown", conclusion: null as string | null,
      steps: [] as { key: string; status: string }[],
    };
  }
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
  return {
    status: job?.status ?? "unknown",
    conclusion: job?.conclusion ?? null,
    steps,
  };
}
