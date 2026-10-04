/** Local fixture access is intentionally disabled on Vercel and unless opted in. */
export function localFixturesEnabled(): boolean {
  return process.env.REASONTRACE_LOCAL_FIXTURES === "1" && !process.env.VERCEL;
}
