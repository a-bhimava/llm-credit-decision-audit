# TypeScript audit-runtime migration

## Current status

The reviewed Python harness remains the executable source of truth for all six audit families,
the exporter, and strict verification. `web/` now contains a private-preview product surface:
the public landing page, a facts-only Audit Studio, encrypted job-storage contracts, a
server-only workflow boundary, and the beginning of the TypeScript conformance layer.

It is intentionally **not live yet**. `TYPESCRIPT_AUDIT_ENGINE_ENABLED` is required in addition
to `LIVE_AUDITS_ENABLED`; without it, the API refuses the request before writing a job or making
a provider call. Do not set the engine flag until the parity gates below are satisfied. A partial
audit must fail closed, never resemble a completed result.

The static evidence ledger is still public at `/evidence` and `/r/*`. Its committed bundles are
not affected by the private-preview runtime.

## Runtime boundary

The planned deployed system is one Vercel Next.js project rooted at `web/`:

```text
browser → /api/audits → encrypted Redis job record → durable workflow → Vertex Gemini
                 ↑                 ↓                         ↓
         HttpOnly session cookie  60 minute TTL         opaque job ID only
```

The browser sends a finite, fictional financial-facts schema. It cannot send names, addresses,
contact details, account IDs, SSNs, free text, or uploads. The server generates any presentation
variants deterministically. The API stores the encrypted intake and progress for 60 minutes;
the browser session owns access through a signed HttpOnly cookie. API responses send
`Cache-Control: no-store`.

The durable workflow receives only the job ID. It decrypts input inside Node-capable steps,
where provider calls, persistence, and budget accounting belong. Do not put applicant content in
workflow arguments, workflow return values, console logs, URL parameters, or event labels.
Workflow-platform retention is governed by Vercel’s platform terms and is not a substitute for
the application’s 60-minute Redis TTL.

## Required private-preview configuration

Set these only in ignored `web/.env.local` for local use or in the Vercel project’s encrypted
environment settings. Never paste a key into a chat, commit one, or use a `NEXT_PUBLIC_` name.

| Variable | Purpose |
| --- | --- |
| `LIVE_AUDITS_ENABLED=true` | Explicitly permits private-preview audit requests. |
| `TYPESCRIPT_AUDIT_ENGINE_ENABLED=true` | Final launch guard; leave unset until parity is complete. |
| `VERTEX_API_KEY` | Initial server-only Vertex/Gemini credential. Replace later with the approved service-account path without changing browser code. |
| `VERTEX_MODEL=gemini-2.5-flash-lite` | Pinned initial model, which must remain in the dated price table. |
| `AUDIT_SESSION_ENCRYPTION_KEY` | Base64-encoded random 32-byte AES key, also used to sign session cookies. |
| `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` | Vercel Marketplace Redis connection for encrypted job records and atomic daily reservations. |
| `AUDIT_MAX_USD_PER_JOB=2` / `AUDIT_DAILY_BUDGET_USD=25` | Deployment controls; code must enforce the same hard defaults if values are absent. |

Use a private Vercel preview while on Hobby. Before anyone outside the personal preview group can
use live audits, upgrade to the appropriate Vercel plan, add an edge/WAF rate-limit rule, and
verify the public-abuse controls in a deployed preview.

## Port order and release gates

1. Port immutable records, exact cents, four-decimal ratio arithmetic, canonical JSON, BLAKE2
   identities, seed derivation, and shared policy/suite data.
2. Generate fixtures from the Python harness and add TypeScript parity tests for IDs, render
   packets, interventions, trajectories, check rows, score summaries, and normalized exports.
3. Port the oracle, reason mapper/repairs, renderers, tools, episode loop, cassette client, and
   each of the six audit families. Keep Python tests green during every slice.
4. Port the dry-run planner and budget admission. It must use the worst-case reason-repair tree,
   reject unpriced models, hard-cap each configuration at $1, hard-cap a job at $2, and reserve
   daily spend atomically before a workflow starts.
5. Add real Vertex calls only inside retryable workflow steps. A `429` is retryable; a malformed
   model response, unpriced model, exhausted budget, or schema violation is a visible terminal
   failure.
6. Compare TypeScript output with Python’s scripted and cassette fixtures. The public runtime can
   be enabled only after the required parity vectors and full Python suite pass.

A live comparison always runs the structured baseline and tool-guided platform on the same
fictional applicant. It must report a configuration comparison for that scenario, not a general
model claim or a population-level fairness result.

## Verification

Run the public-site build and its dynamic-boundary guard from `web/`:

```bash
./node_modules/.bin/tsc --noEmit
./node_modules/.bin/next build
node scripts/assert-security-boundaries.mjs
```

The build should list `/audit` as static, `/evidence` and `/r/*` as static/SSG, and only the
workflow internals plus `/api/audits` as dynamic. The boundary assertion rejects client modules
that name a credential-shaped public variable or a server secret, and requires API routes to
send `no-store` responses.

The historical Python run/export/verify commands remain the release authority until the
TypeScript parity gate is complete.
