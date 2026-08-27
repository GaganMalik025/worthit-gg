/**
 * PostHog, initialised once, client-side (BUILD_PLAN 3.3 / PRD F7).
 *
 * `instrumentation-client.ts` is Next's own file convention for client-side
 * setup and is what PostHog's current Next.js guide uses for BOTH routers. It
 * is stable from Next 15.3; this app is on 15.5.22, so there is no
 * `providers.tsx` and no `experimental.clientInstrumentationHook` - and no
 * `next.config.*` is needed to enable it.
 *
 * THE KEY GUARD IS LOAD-BEARING, not defensive decoration. `.env.local` is
 * gitignored, so CI (`npm ci && npm test`, no env) and any fresh checkout have
 * no key. Calling init with `undefined` gives an SDK pointed at nothing that
 * still queues and retries; not calling it at all makes `capture()` in
 * lib/analytics.ts a no-op by the same test. Analytics failing silently is
 * correct - it must never be able to break a verdict page.
 *
 * `defaults` pins a dated behaviour snapshot so a future posthog-js upgrade
 * cannot silently change what we capture. '2026-08-29' is the newest value
 * `ConfigDefaults` declares in the installed 1.419.4
 * (node_modules/@posthog/types/dist/posthog-config.d.ts) and includes every
 * earlier snapshot. What it buys us here:
 *
 *   - `capture_pageview: 'history_change'` - autocaptured $pageview/$pageleave
 *     that follow App Router client-side navigation. THIS IS WHY THERE IS NO
 *     "session" EVENT: it is already covered, for free, and better.
 *   - `internal_or_test_user_hostname: /^(localhost|127\.0\.0\.1)$/` - events
 *     from `npm run dev` are still SENT, but tagged `$internal_or_test_user:
 *     true`. PostHog's live events view filters those out by default, so
 *     locally triggered events look missing until that filter is turned off.
 *     Kept on: it is the right behaviour for production hygiene.
 *
 * Nothing here enables session replay, exception autocapture or web vitals -
 * they stay off, which is what keeps this inside the free tier (CLAUDE.md,
 * total budget ₹0).
 */

import posthog from "posthog-js";

// Referenced as a literal `process.env.X` member access, NOT destructured -
// that is the form Next inlines at build time. A destructured read is
// `undefined` in the browser bundle.
const KEY = process.env.NEXT_PUBLIC_POSTHOG_KEY;

if (KEY) {
  posthog.init(KEY, {
    // US cloud INGESTION subdomain, not the dashboard domain.
    api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST,
    defaults: "2026-08-29",
  });
}
