/**
 * ADMISSION: every refusal charges nothing and dispatches nothing.
 *
 * Offline: all IO is injected, and the GitHub helpers below run against a stubbed
 * fetch. No network, no token, no quota. See lib/admission.ts for the reasoning.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  admit,
  alreadyRunning,
  hashClient,
  inSearchIndex,
  resetSearchIndexForTest,
  type AdmissionDeps,
} from "../admission";
import {
  dispatchGeneration,
  listRuns,
  listRunsStrict,
  readQuota,
  verdictExists,
  writeQuota,
  type RunInfo,
} from "../github";
import { EST_COST, IP_LIMIT_PER_HOUR, LIVE_RESERVE, quotaDay } from "../quota";

const TODAY = quotaDay(new Date().toISOString());
const APPID = "413150";
const CLIENT = "a1b2c3d4e5f60718";

const run = (over: Partial<RunInfo> = {}): RunInfo => ({
  id: 1,
  status: "completed",
  conclusion: "failure",
  created_at: new Date().toISOString(),
  appid: APPID,
  ...over,
});

function deps(over: Partial<AdmissionDeps> = {}) {
  const writeQuota = vi.fn(async () => {});
  const dispatch = vi.fn(async () => {});
  const d: AdmissionDeps = {
    inSearchIndex: async () => true,
    verdictExists: async () => ({ found: false }),
    readQuota: async () => ({ date: TODAY, live_used: 0 }),
    listRuns: async () => [],
    runOutcome: async () => "stage_failed",
    fetchVerdictCost: async () => null,
    writeQuota,
    dispatch,
    ...over,
  };
  return { d, writeQuota: d.writeQuota as typeof writeQuota, dispatch: d.dispatch as typeof dispatch };
}

async function refused(over: Partial<AdmissionDeps>) {
  const { d, writeQuota, dispatch } = deps(over);
  const out = await admit(APPID, CLIENT, d);
  expect(writeQuota).not.toHaveBeenCalled();
  expect(dispatch).not.toHaveBeenCalled();
  return out;
}

describe("admit: the normal miss", () => {
  it("reserves first, then dispatches, carrying the charged ledger", async () => {
    const order: string[] = [];
    const { d, writeQuota, dispatch } = deps({
      writeQuota: vi.fn(async () => { order.push("write"); }),
      dispatch: vi.fn(async () => { order.push("dispatch"); }),
    });
    const out = await admit(APPID, CLIENT, d);
    expect(out.body).toEqual({ state: "dispatched", appid: 413150 });
    expect(order).toEqual(["write", "dispatch"]);
    const written = writeQuota.mock.calls[0][0 as never] as unknown as Record<string, unknown>;
    expect(written.live_used).toBe(EST_COST);
    expect(dispatch.mock.calls[0][1 as never]).toEqual(written);
  });
});

describe("admit: refusals charge nothing and dispatch nothing", () => {
  it("a title outside the search index", async () => {
    const out = await refused({ inSearchIndex: async () => false });
    expect(out.status).toBe(404);
  });

  it("a title deployed on main, which is the audited-verdict case", async () => {
    const out = await refused({
      verdictExists: async () => ({ found: true, source: "main" }),
    });
    expect(out.body.state).toBe("exists");
    expect(out.body.source).toBe("main");
  });

  it("a title only on the verdicts branch", async () => {
    const out = await refused({
      verdictExists: async () => ({ found: true, source: "verdicts" }),
    });
    expect(out.body.state).toBe("exists");
  });

  it("a title already running joins that run", async () => {
    const out = await refused({
      listRuns: async () => [run({ status: "in_progress", conclusion: null })],
    });
    expect(out.body).toEqual({ state: "dispatched", appid: 413150, joined: true });
  });

  it("a dispatch still inside its grace window joins too", async () => {
    const out = await refused({
      readQuota: async () => ({
        date: TODAY,
        live_used: 13,
        dispatched: { [APPID]: new Date().toISOString() },
      }),
    });
    expect(out.body.joined).toBe(true);
  });

  it("an exhausted reserve", async () => {
    const out = await refused({
      readQuota: async () => ({ date: TODAY, live_used: LIVE_RESERVE }),
    });
    expect(out.body.state).toBe("queue_fallback");
    expect(out.body.reason).toBe("reserve_exhausted");
  });

  it("a client over the hourly limit", async () => {
    const hour = `${TODAY}T${new Date().toLocaleString("en-GB", {
      timeZone: "America/Los_Angeles", hour: "2-digit", hour12: false,
    }).slice(0, 2)}`;
    const out = await refused({
      readQuota: async () => ({
        date: TODAY,
        live_used: 0,
        by_ip_hour: { [`${CLIENT}|${hour}`]: IP_LIMIT_PER_HOUR },
      }),
    });
    expect(out.body.reason).toBe("ip_limited");
  });
});

describe("admit: anything it cannot answer falls back, never guesses", () => {
  const boom = async () => { throw new Error("down"); };
  for (const [name, over] of [
    ["the index", { inSearchIndex: boom }],
    ["the verdict lookup", { verdictExists: boom }],
    ["the ledger", { readQuota: boom }],
    ["the run list", { listRuns: boom }],
  ] as [string, Partial<AdmissionDeps>][]) {
    it(`${name} is unreadable`, async () => {
      const out = await refused(over);
      expect(out.body).toEqual({ state: "queue_fallback", reason: "unverifiable" });
    });
  }

  it("a failed ledger write stops the dispatch", async () => {
    const { d, dispatch } = deps({ writeQuota: boom });
    const out = await admit(APPID, CLIENT, d);
    expect(out.body.reason).toBe("ledger_unwritable");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("a failed dispatch leaves the reservation booked", async () => {
    const { d, writeQuota } = deps({ dispatch: boom });
    const out = await admit(APPID, CLIENT, d);
    expect(out.body.reason).toBe("dispatch_failed");
    expect(writeQuota).toHaveBeenCalledTimes(1);
  });
});

describe("alreadyRunning", () => {
  const now = Date.parse("2026-08-16T10:00:00Z");
  const at = (ms: number) => new Date(now + ms).toISOString();

  it("a dispatch past its grace window with no run is lost, so may retry", () => {
    const s = { dispatched: { [APPID]: at(-200_000) } };
    expect(alreadyRunning(APPID, s, [], now)).toBe(false);
  });

  it("a fast failure after the dispatch may retry inside the window", () => {
    const s = { dispatched: { [APPID]: at(-30_000) } };
    expect(
      alreadyRunning(APPID, s, [run({ created_at: at(-29_000) })], now),
    ).toBe(false);
  });

  it("an older finished run does not count as this dispatch's run", () => {
    const s = { dispatched: { [APPID]: at(-30_000) } };
    expect(
      alreadyRunning(APPID, s, [run({ created_at: at(-3_600_000) })], now),
    ).toBe(true);
  });

  it("another title's active run is not this title's", () => {
    expect(
      alreadyRunning(APPID, {}, [run({ appid: "1", status: "queued" })], now),
    ).toBe(false);
  });
});

describe("hashClient: the address stays out of repository state", () => {
  const IP = "203.0.113.7";

  it("is stable for one client and differs between clients", () => {
    expect(hashClient(IP, "k")).toBe(hashClient(IP, "k"));
    expect(hashClient(IP, "k")).not.toBe(hashClient("203.0.113.8", "k"));
  });

  it("is keyed, so it cannot be reversed by hashing every address", () => {
    expect(hashClient(IP, "k")).not.toBe(hashClient(IP, "other"));
  });

  it("no raw address reaches the ledger or the dispatch", async () => {
    const { d, writeQuota, dispatch } = deps();
    await admit(APPID, hashClient(IP, "k"), d);
    const sent = JSON.stringify([writeQuota.mock.calls, dispatch.mock.calls]);
    expect(writeQuota).toHaveBeenCalled();
    expect(sent).not.toContain(IP);
    expect(sent).toContain(hashClient(IP, "k"));
  });
});

describe("inSearchIndex", () => {
  const shard = (ids: number[]) =>
    new Response(JSON.stringify({ t: ids.map((i) => [i, `game ${i}`]) }));

  afterEach(resetSearchIndexForTest);

  it("finds a title in either shard and rejects the rest", async () => {
    const f = vi.fn(async (u: string) =>
      u.includes("core") ? shard([1]) : shard([2])) as unknown as typeof fetch;
    expect(await inSearchIndex("1", "https://x", f)).toBe(true);
    expect(await inSearchIndex("2", "https://x", f)).toBe(true);
    expect(await inSearchIndex("3", "https://x", f)).toBe(false);
  });

  it("a shard that will not load is an error, not a 'no'", async () => {
    const f = vi.fn(async (u: string) =>
      u.includes("core") ? shard([1]) : new Response("", { status: 500 })) as unknown as typeof fetch;
    await expect(inSearchIndex("1", "https://x", f)).rejects.toThrow();
  });
});

describe("the GitHub helpers fail loudly", () => {
  const respond = (...rs: Response[]) => {
    const f = vi.fn(async () => rs.shift() as Response);
    vi.stubGlobal("fetch", f);
    vi.stubEnv("GH_DISPATCH_TOKEN", "t");
    vi.stubEnv("GH_REPO", "o/r");
    return f;
  };
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });
  const variable = (value: string) =>
    new Response(JSON.stringify({ value }), { status: 200 });

  it("readQuota: corrupt JSON throws rather than reading as zero spend", async () => {
    respond(variable("{not json"));
    await expect(readQuota()).rejects.toThrow();
  });

  it("readQuota: a non-object throws", async () => {
    respond(variable("[1,2]"));
    await expect(readQuota()).rejects.toThrow(/not an object/);
  });

  it("readQuota: a variable that does not exist yet is an empty ledger", async () => {
    respond(new Response("", { status: 404 }));
    expect(await readQuota()).toEqual({});
  });

  it("writeQuota: a rejected PATCH throws and does not try to create", async () => {
    const f = respond(new Response("", { status: 403 }));
    await expect(writeQuota({})).rejects.toThrow(/403/);
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("writeQuota: a missing variable is created, and a failed create throws", async () => {
    respond(new Response("", { status: 404 }), new Response("", { status: 403 }));
    await expect(writeQuota({})).rejects.toThrow(/create/);
    respond(new Response("", { status: 404 }), new Response("", { status: 201 }));
    await expect(writeQuota({})).resolves.toBeUndefined();
  });

  it("dispatchGeneration sends no client address", async () => {
    const f = respond(new Response(null, { status: 204 }));
    await dispatchGeneration(1, { date: TODAY, live_used: 13 });
    const body = JSON.parse((f.mock.calls[0] as unknown as [string, RequestInit])[1].body as string);
    expect(Object.keys(body.client_payload).sort()).toEqual(["appid", "quota"]);
  });

  it("verdictExists: the deployed file answers without GitHub", async () => {
    const f = respond(new Response(null, { status: 200 }));
    expect(await verdictExists("1", "https://x")).toEqual({ found: true, source: "main" });
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("verdictExists: 404 everywhere is absent", async () => {
    respond(
      new Response(null, { status: 404 }),
      new Response("", { status: 404 }),
      new Response("", { status: 404 }),
    );
    expect(await verdictExists("1", "https://x")).toEqual({ found: false });
  });

  it("verdictExists: a GitHub failure is unknown, not absent", async () => {
    respond(new Response(null, { status: 404 }), new Response("", { status: 503 }));
    await expect(verdictExists("1", "https://x")).rejects.toThrow(/503/);
  });

  it("the run list: strict throws where the status path gets []", async () => {
    respond(new Response("", { status: 500 }));
    await expect(listRunsStrict()).rejects.toThrow(/500/);
    respond(new Response("", { status: 500 }));
    expect(await listRuns()).toEqual([]);
  });
});
