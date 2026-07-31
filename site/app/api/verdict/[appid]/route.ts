import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/**
 * Serves a freshly generated verdict from the `verdicts` branch, before the
 * nightly merge makes it part of the build.
 *
 * Proxied rather than linked directly: raw.githubusercontent is 60 req/hr
 * unauthenticated, and jsDelivr caches branch refs ~12h, which would defeat the
 * point. With the token this is 5,000/hr, and we set our own cache headers.
 */
export async function GET(
  _req: NextRequest,
  { params }: { params: Promise<{ appid: string }> },
) {
  const { appid } = await params;
  if (!/^\d+$/.test(appid)) {
    return NextResponse.json({ error: "bad appid" }, { status: 400 });
  }
  const repo = process.env.GH_REPO;
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!repo || !token) {
    return NextResponse.json({ error: "not configured" }, { status: 500 });
  }

  const res = await fetch(
    `https://api.github.com/repos/${repo}/contents/site/public/verdicts/${appid}.json?ref=verdicts`,
    {
      headers: {
        accept: "application/vnd.github.raw",
        authorization: `Bearer ${token}`,
        "x-github-api-version": "2022-11-28",
      },
      cache: "no-store",
    },
  );
  if (!res.ok) {
    return NextResponse.json({ error: "not found" }, { status: 404 });
  }
  return new NextResponse(await res.text(), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, s-maxage=300, stale-while-revalidate=3600",
    },
  });
}
