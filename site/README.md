# site/ — WorthIt.gg (Next.js, static)

## Tests

```bash
cd site
npm install      # once
npm test         # the dual-path contract test
npm run test:watch
```

### What `npm test` protects

A verdict page can be built two ways, and both feed the same component:

| path | when | source |
|---|---|---|
| `loadVerdictStatic` | catalog titles, prerendered at build | `public/verdicts/` |
| `loadVerdictProxied` | titles generated live, not yet merged | `verdicts` branch via `/api/verdict/` |

`lib/__tests__/verdict-render.contract.test.tsx` asserts the two produce
identical parsed data **and** byte-identical markup. Only freshly generated
titles take the proxied path, so a divergence would show up on the
least-watched pages on the site — this is what makes it loud instead.

**When it runs:** on every push/PR touching `site/` or `public/verdicts/`
(`.github/workflows/ci.yml`), and again as a **merge gate** in
`publish-verdicts.yml` before verdicts are promoted to `main`. A broken dual
path cannot reach `main`; the verdicts simply stay on the `verdicts` branch,
still served live.

**Run it against all fixtures, not one.** The test began with a single Kenshi
fixture and an injected bug walked straight through it — Kenshi has no null
`summary`, so the divergent branch never executed. It now runs across all
committed verdicts plus a synthetic edge case, and asserts the fixture set
still covers the muted/nullable branches.

**Known limit:** `renderToStaticMarkup` compares server markup and data, not
post-hydration behaviour. If either loader grows client-side logic, add a
hydration-level companion test.
