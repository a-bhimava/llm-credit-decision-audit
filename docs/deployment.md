# Evidence ledger and private-preview deployment

The evidence ledger lives in `web/`. Its evidence routes build every known run, check, and pair
as static HTML from the reviewed projection in `web/public/runs/`; they do not read raw `runs/`
artifacts or contact a provider. The same Vercel project now also includes a gated private Audit
Studio API and durable workflow path. It is disabled by default and must not be exposed publicly
until the TypeScript conformance gate is complete.

## Local release check

Use Node 22 and the package-manager version recorded in `web/package.json`:

```bash
cd web
corepack enable
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```

`pnpm build` runs Next's production build and then `scripts/assert-security-boundaries.mjs`. The
assertion rejects public credential-shaped environment variables and server-secret references in
client modules, and requires API handlers to send `Cache-Control: no-store`. Build output must
keep `/evidence` and `/r/*` static/SSG; the private API and workflow internals are expected to
be dynamic.

The `Evidence site` GitHub Actions job repeats those checks on every pull request and `main`
push. Keep that job required in the repository's branch-protection rule before enabling
automatic production deployment.

## Vercel Git integration

Create or import a Vercel project from this GitHub repository, then set:

| Setting | Value |
| --- | --- |
| Framework preset | Next.js (auto-detected) |
| Root Directory | `web` |
| Install Command | default (`pnpm install --frozen-lockfile`) |
| Build Command | default (`pnpm build`) |
| Node.js version | 22 |
| Environment variables | none for evidence-only deployment; private-preview values are documented separately |

With Git integration enabled, Vercel uses `main` for the production deployment and creates a
preview deployment for each pull request. The public evidence ledger needs no provider key. The
private preview may use server-only Vercel environment secrets after the TypeScript engine is
complete and its launch flags have been intentionally set; see
[`typescript-runtime-migration.md`](typescript-runtime-migration.md).

Before treating the production URL as official, enable branch protection for `main` and require
the GitHub `Evidence site` and Python `test` checks. This makes a passing static build a
precondition for the merge that Vercel deploys.

## Headers and public evidence access

`web/vercel.json` applies a restrictive content-security policy, disables MIME sniffing, limits
browser permissions, and uses a strict referrer policy. It deliberately sends
`Access-Control-Allow-Origin: *` only for `/runs/**`. That permits an independent notebook or
browser tool to fetch the committed evidence bundle and recompute claims; it does not grant
access to any raw run data because raw artifacts are not deployed.

## Updating the data later

Follow the private real-provider runbook to produce and strictly verify a reviewed projection
before changing `web/public/runs/`. Then run the local release check above and inspect the
generated overview, pair, check, validation, and integrity routes. The static build enumerates
all routes from `runs/index.json`, so a malformed or missing referenced artifact fails before
deployment.

This deployment check validates the site and its committed projection. The Phase 11 evidence
freshness workflow—fresh scripted run, re-export, strict verification, and a controlled bundle
diff—is intentionally a separate gate because its recorded source-commit provenance needs to
be reconciled with the commit that adds the regenerated projection.
