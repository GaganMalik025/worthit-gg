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
export async function verdictExists(appid: number | string): Promise<boolean> {
  const res = await gh(
    `/contents/site/public/verdicts/${appid}.json?ref=verdicts`,
    { method: "HEAD" },
  );
  if (res.ok) return true;
  // HEAD is not supported on every contents path; fall back to a cheap GET
  if (res.status === 404) return false;
  const get = await gh(`/contents/site/public/verdicts/${appid}.json?ref=verdicts`);
  return get.ok;
}

export interface RunInfo {
  id: number;
  status: string;
  created_at: string;
  appid: string | null;
}

/** Runs of the generate workflow that have not finished, oldest first. */
export async function listActiveRuns(): Promise<RunInfo[]> {
  const out: RunInfo[] = [];
  for (const status of ["queued", "in_progress"]) {
    const res = await gh(
      `/actions/workflows/generate-verdict.yml/runs?status=${status}&per_page=50`,
    );
    if (!res.ok) continue;
    const { workflow_runs = [] } = (await res.json()) as {
      workflow_runs: { id: number; status: string; created_at: string }[];
    };
    out.push(...workflow_runs.map((r) => ({ ...r, appid: null })));
  }
  return out.sort((a, b) => a.created_at.localeCompare(b.created_at));
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
      status:
        s.conclusion === "success"
          ? "completed"
          : s.conclusion
            ? "failed"
            : s.status === "in_progress"
              ? "in_progress"
              : "pending",
    }));
  return { status: job?.status ?? "unknown", steps };
}
