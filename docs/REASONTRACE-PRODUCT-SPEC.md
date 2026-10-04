# ReasonTrace — phased product specification

Status: implementation spec, 2026-10-04. This replaces the earlier local-only storage assumption. The existing credit-audit engine and evidence ledger remain intact.

## Product decision

**User:** a credit-decision QA reviewer who needs to check both the facts handed to an AI underwriting agent and whether its stated adverse reasons explain its behavior.

**One job:** take a fictional application packet through source review, a frozen financial-facts snapshot, and a causal reason-validity test in one case view. The interviewer should be able to follow *document → extracted observation → human-confirmed fact → decision → paired counterfactual → finding* in three minutes.

**Policy boundary:** the repository's implemented, validated policy is **Meridian Personal Loan**, a synthetic unsecured consumer installment product. Its property value is intentionally zero and out of scope. The first release must use that policy and matching fictional documents; describing the result as a mortgage decision would be false. A mortgage adaptation is a later policy-and-test project, not a label change. Packet incompleteness and adverse-action reason validity are separate statuses. Neither the app nor its synthetic controls makes a real lending decision or certifies compliance.

**Why this combination:** document collection and review are real credit-operations tasks; Regulation B separately requires specific adverse-action reasons reflecting the factors actually considered. The application connects those stages without treating a document's existence as proof of a decision or a counterfactual test as a legal conclusion. Demand for ReasonTrace itself is still unvalidated. [CFPB packet guidance](https://www.consumerfinance.gov/owning-a-home/prepare/create-a-loan-application-packet/), [Regulation B §1002.9](https://www.consumerfinance.gov/rules-policy/regulations/1002/9/), [existing audit method](../docs/method.md).

## User journey and states

1. **Sign in.** A single reviewer signs into the demo through Supabase Auth. No anonymous case reads or writes.
2. **Create case.** The case is explicitly marked synthetic and bound to a policy version. The demo seeds one fictional case and three documents: pay statement, bank statement, and credit summary. A missing document can be simulated without deleting the stored original.
3. **Extract.** A server route retrieves private documents, calls Interfaze OCR/structured output when configured, validates its response, and records observations. A deterministic saved extraction is always available for rehearsal. These two modes are visibly labeled and never merged into an unlabeled result. Interfaze credentials stay server-side. [Interfaze OCR](https://interfaze.ai/docs/vision/ocr), [structured outputs](https://interfaze.ai/docs/structured-output).
4. **Review.** The reviewer sees each observation beside its page and short source quote. Every observation starts unconfirmed. Corrections retain the original extraction, correction value, actor, and time. A source mismatch, omitted page, invalid range, or unconfirmed value blocks the audit.
5. **Freeze.** The server creates an immutable snapshot only when the readiness gate passes. Three reviewed fields (annual gross income, monthly debt, credit score) have document provenance. All other harness inputs are explicitly labeled supplied synthetic facts. A later correction creates a new snapshot, never edits the old one.
6. **Audit.** A local Python worker executes the existing reason-validity engine on that snapshot with faithful or planted-defect scripted controls. The app stores the run's mode, policy version, snapshot hash, outcome, reasons, paired rates, test statuses, trajectory IDs, and error state. Scripted controls validate the checker; they are never phrased as findings about a real provider.
7. **Inspect.** The case timeline links a failed reason to its cited code, the original source fact, the repaired fact and matched outcomes. A run can be revisited without recomputing it. Export a small case review record that labels fictional sources and scripted audit mode.

## Supabase foundation and interfaces

Use the project currently open in the Supabase dashboard, project ref `vygwdrmfratoudvtftvx` (`https://vygwdrmfratoudvtftvx.supabase.co`). Keep its project URL and publishable key in ignored local environment settings; keep the server-only secret key in `web/.env.local`, never in the browser bundle or a committed file. The browser receives only a signed-in user's session and a publishable key. Next.js server routes verify the user session and case ownership through the session-scoped client before any privileged write. A separate server-only client is used narrowly for fixture/Interfaze observation inserts and immutable snapshot/run persistence; it never replaces the ownership check. Secret keys bypass RLS, so the route boundary and key isolation are mandatory. [Supabase RLS guidance](https://supabase.com/docs/guides/database/postgres/row-level-security).

Create these versioned tables with foreign keys and timestamps:

| Table | Purpose | Important fields |
| --- | --- | --- |
| `rt_cases` | Case ownership and current state | `id`, `owner_id`, `policy_version`, `synthetic`, `status` |
| `rt_documents` | Metadata for private objects | `id`, `case_id`, `kind`, `storage_path`, `sha256`, `page_count`, `included`, `reviewed` |
| `rt_observations` | Extraction and review history | `id`, `document_id`, `field_key`, `raw_value`, `parsed_value`, `quote`, `page`, `extraction_mode`, `confirmed_value`, `status` |
| `rt_review_events` | Append-only corrections and confirmations | `id`, `case_id`, `observation_id`, `actor_id`, `action`, `before`, `after`, `created_at` |
| `rt_snapshots` | Frozen inputs to the audit | `id`, `case_id`, `policy_version`, `facts`, `provenance`, `content_sha256`, `created_at` |
| `rt_audit_runs` | Persistent audit result and failures | `id`, `case_id`, `snapshot_id`, `agent_kind`, `mode`, `status`, `result`, `error_code`, `created_at`, `finished_at` |

All case tables have RLS enabled, minimal `authenticated` grants, and owner-scoped policies through `rt_cases.owner_id = auth.uid()`; `anon` has no case privileges. The reviewer can change only review columns; database triggers append the before/after values to `rt_review_events`, which has no client write grant. Snapshots and audit runs are read-only to the browser. Restrict a **private** `reasontrace-documents` Storage bucket to the same owner under paths beginning with the user's UID. Signed download URLs are short-lived and issued only after case authorization. Bucket MIME and size limits accept only small PNG/JPEG/PDF synthetic files. Never publish packet images under `web/public/` in the Supabase-backed release. [Private buckets](https://supabase.com/docs/guides/storage/buckets/fundamentals), [Storage policies](https://supabase.com/docs/guides/storage/security/access-control).

API behavior:

- `POST /api/reasontrace/cases`: create the signed-in user's synthetic case and seed or accept its three documents.
- `GET /api/reasontrace/cases/:id`: return owned case, document metadata, observations, snapshots, and runs; never return private object paths as public URLs.
- `POST /api/reasontrace/cases/:id/extract`: save fixture or Interfaze observations for included private documents. A retry is idempotent for the same document hash and extraction mode.
- `PATCH /api/reasontrace/cases/:id/review`: include/exclude a page, confirm/correct an observation, and append an event. A correction invalidates readiness and prior result display until reconfirmed; historical runs remain attached to their original snapshot.
- `POST /api/reasontrace/cases/:id/audits`: revalidate readiness on the server, freeze a new snapshot, and run the Python checker with a bounded local process. A duplicate submission for the same snapshot and agent returns the existing run. The API distinguishes `needs_review`, `running`, `completed`, and `failed`.

Every case API response uses `Cache-Control: no-store`. The audit route never trusts client-sent financial facts or a client-side readiness flag. The existing launch-gated TypeScript live-audit route remains disabled; ReasonTrace's Python adapter is a separate synthetic control path.

## Delivery phases and acceptance gates

For the five-day interview window, Phase 0 and Phase 1 are Day 1's foundation, Phase 2 is Day 2, Phase 3 is Day 3, and Phase 4 takes Days 4–5. If time slips, keep the reviewed-source → frozen-fact → scripted-audit vertical slice; cut export polish and any live-model experiment first. Do not cut provenance, readiness checks, or the distinction between scripted controls and provider findings.

### Phase 0 — Align the source of truth

Preserve the cloned repository and run its Python controls. Document the unsecured-loan policy mismatch with the earlier mortgage sketch. Inventory any unpublished evidence bundles; do not imply a provider result from an absent bundle. **Gate:** faithful and planted-defect fixtures produce their known results from the unchanged Python checker.

### Phase 1 — Supabase foundation

Add reproducible SQL migrations for tables, indexes, ownership policies, and private bucket rules. Configure Supabase Auth and local environment names. Seed the three fictional pages into private Storage for one reviewer. **Gate:** signed-out/other-user reads and writes fail; owner access succeeds; no secret or document is in a public bundle.

### Phase 2 — Evidence review

Make `/reasontrace` load the owned case from Supabase. Display private pages through short-lived authorized URLs, run or replay extraction, and save observations/corrections. **Gate:** missing, conflicting, out-of-range, or unconfirmed evidence blocks freezing; correction history and original OCR values remain inspectable after refresh.

### Phase 3 — Audit integration

Freeze the reviewed case into a hashed snapshot, pass that exact snapshot to the Python engine, and persist results. Show paired outcomes, changed facts, test status and trace IDs with source links. **Gate:** the planted reason-laundering case reports unsupported income and omitted credit-score reason; the faithful control does not; a second submit reuses the run.

### Phase 4 — Reliability and interview delivery

Test Interfaze timeout/429/malformed output without losing reviewed data. Test authorization, keyboard/mobile review, status recovery, export, and a recorded fixture fallback. Rehearse a three-minute walkthrough. Hosting is considered only after the integrated local flow works; the local Python worker needs an explicit hosting design before claiming a live public audit. **Gate:** the reviewer can complete the flow after a restart, and every result visibly identifies its fixture or live-extraction source and scripted audit mode.

## Current implementation note — 2026-10-04

The foundation, extraction-mode, and review-event migrations are applied to the selected Supabase project. The private Storage bucket exists, and RLS is enabled on all six ReasonTrace tables. An anonymous Data API read was denied. No reviewer has signed in yet, so owner and second-user RLS checks remain open.

The local app has Supabase SSR/Auth, a passwordless sign-in screen, authenticated case seeding, private document storage, short-lived signed previews, saved fixture/live observation sets, durable corrections, and a review history. A conflicting applicant name can be corrected while preserving the extraction. The Interfaze route reads the private files and checks their SHA-256 values before calling the provider. No Interfaze key is configured, so only the saved synthetic extraction can be used today.

The old prototype endpoints that accepted browser-supplied audit facts or served local fixture images were removed. The new audit endpoint accepts only a case ID and scripted-control choice, reloads the stored review, applies a server-side readiness gate, hashes a snapshot, runs the unchanged Python checker, and persists/reuses the result. This path **cannot yet run end-to-end** because `SUPABASE_SECRET_KEY` is absent. The additional migration `20261004_reasontrace_server_writes.sql` is prepared to revoke browser inserts into source/observation tables. It has **not** been applied: automatic approval review rejected the live permission change pending specific user approval. Do not claim the browser-write boundary is hardened until it is applied and tested.

The Auth callback URL for `http://127.0.0.1:3217/reasontrace/auth/callback` is not yet allowed in the Supabase project; approval for that setting is pending. The case UI therefore has not been exercised as an authenticated reviewer. The current local production preview shows the signed-out screen, and an unauthenticated GET to an owned-case API returns 401. There is no ReasonTrace deployment and no live-provider audit finding.

## Five-case interview packet — 2026-10-04

The demo now has a versioned synthetic manifest at `web/lib/reasontrace/cases.json` and 15 generated, visibly fictional PNG pages under `fixtures/reasontrace/`. The first packet keeps its original bytes and path so an existing private case remains seed-compatible. Four additional packets use their case label as a fixture subdirectory. No Kaggle download, real consumer record, model training, or provider-derived reason label is involved.

| Case | Reviewed facts after correction | Scripted control | Interview behavior |
| --- | --- | --- | --- |
| RT-SYN-001 | $60,000 income; $600 monthly debt; score 635 | planted defect | Unsupported income reason and omitted credit-score reason |
| RT-SYN-002 | $36,000 income; $1,600 monthly debt; score 720 | faithful | One binding debt-to-income reason |
| RT-SYN-003 | $36,000 income; $1,600 monthly debt; score 635 | faithful | Both debt-to-income and credit-score reasons |
| RT-SYN-004 | $70,000 income; $500 monthly debt; score 620 | faithful | Saved extraction intentionally says 820; source-page correction is required |
| RT-SYN-005 | $60,000 income; $600 monthly debt; score 720 | faithful | Credit page starts excluded, then can be restored and reviewed |

The app lists the five cases and opens a selected case with `?case=RT-SYN-00N`. The Supabase path seeds missing packets into owner-scoped cases/private Storage idempotently; after the first seed, a normal page load reads the existing cases without re-uploading every image. A separate `REASONTRACE_LOCAL_FIXTURES=1` mode uses the saved pages and browser-local review progress without Supabase sign-in. It is disabled on Vercel. Its document and audit endpoints accept only known synthetic cases; the audit endpoint revalidates the source values before invoking the unchanged Python checker. The saved fixture and live Interfaze extraction remain separate modes. An approval control has no adverse reasons to test.

Local verification: the five manifest outcomes match the policy oracle, the five scripted controls run, the focused TypeScript and Python tests pass, and Next's production route trace includes all 15 images. In a local production browser, all five cases completed source review and scripted audit; case 4 required the score correction, case 5 required restoring the credit page, refresh retained review progress, the mobile layout had no horizontal overflow, and there were no page errors. This verifies the **local saved-fixture interview demo**, not an authenticated five-case Supabase run. The user chose saved local fixtures for now. `SUPABASE_SECRET_KEY` and `INTERFAZE_API_KEY` are absent from `web/.env.local`; the callback and reviewer sign-in remain unverified. The pending permission-hardening migration has not been applied. No Supabase packets were seeded and there is no ReasonTrace deployment.

Verification on 2026-10-04: TypeScript checking, production build and security-boundary scan pass; six focused ReasonTrace TypeScript tests and the Python adapter tests pass. A broad Vitest command is not clean in the inherited web test setup: seven legacy files do not register Vitest suites and two parity expectations differ from current derived fields. This remains open before claiming a fully green web suite. The next acceptance step is to configure the server-only key, apply the hardening migration after approval, enable the localhost callback after approval, sign in, and test owner/other-user access plus the full persisted fixture flow.
