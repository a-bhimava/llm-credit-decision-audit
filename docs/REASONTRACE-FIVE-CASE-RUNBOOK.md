# ReasonTrace five-case interview runbook

These are invented **Meridian Personal Loan** cases. The pages are not real borrower records or bureau reports. The audit agent is a scripted known-answer control, not an Interfaze-hosted credit decision.

## Before the interview

1. For the saved local demo, set `REASONTRACE_LOCAL_FIXTURES=1` in ignored `web/.env.local`. No Supabase or Interfaze key is needed. This mode is disabled on Vercel. For the later Supabase path, the publishable key is used by the browser; `SUPABASE_SECRET_KEY` is server-only and must never be sent in chat or committed. `INTERFAZE_API_KEY` is optional for live extraction, and the localhost Auth callback must be allowed in Supabase.
2. Generate or verify the 15 PNGs with `python3 scripts/generate_reasontrace_docs.py` from the repository root. The first case retains the original three files; the other cases have labeled subdirectories.
3. Run `PYTHONPATH=src .venv/bin/python -m pytest -q tests/unit/test_reasontrace_demo.py`; then in `web/`, run `pnpm typecheck`, `pnpm exec vitest run tests/unit/reasontrace*.test.ts`, and `pnpm build`.
4. Start `web/` with `pnpm exec next start -H 127.0.0.1 -p 3217` and visit `http://127.0.0.1:3217/reasontrace`. In local mode there is no sign-in or upload. Verify that the five case buttons appear and each page preview has its synthetic footer.
5. For each case, mark the included pages reviewed, confirm the three financial fields, and run the recommended scripted control. The source field and case label should remain correct after refresh. For case 4, correct the saved score from 820 to the visible 620. For case 5, include the stored credit page before reviewing it. Open **Review memo** to inspect or download a plain-text source-to-finding record. Revisit the direct link `?case=RT-SYN-00N` for each case. Use **Restart this case** in local mode when you need to replay one packet without clearing the others.

## Three-minute path

- Open case 1. Show the credit summary's 635 score, confirm facts, run the planted-defect control, and follow **Source to finding** from the page quote to the omitted credit-score replay. The path opens the representative paired check; use the separate finding action to inspect the fabricated income reason. Expand the review memo if a full text record is useful.
- Open case 4. Show 820 in the saved extraction against 620 on the page; explain why the audit stays blocked and make the correction.
- Open case 5. Show that excluding the credit page blocks the audit; restore it, review it, and show that an approval has no adverse reason to test.
- Use cases 2 and 3 for follow-up questions about one versus two binding reasons and paired counterfactual checks.

The **saved fixture** is the stable interview path and was browser-rehearsed locally on all five cases. Local review progress stays in this browser. On the separate Supabase path, “Run with Interfaze” makes a server-side OCR/structured-output request only when configured; it creates a separately labeled extraction set and does not turn scripted audit controls into provider findings. Do not claim the authenticated Supabase path was rehearsed until it actually succeeds.
