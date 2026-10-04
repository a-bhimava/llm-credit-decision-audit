import { spawn } from "node:child_process";
import { resolve } from "node:path";

export function runPython(reviewed: Record<string, number>, agent: "faithful" | "laundering",
  caseLabel: string, applicantName: string): Promise<Record<string, unknown>> {
  return new Promise((resolveResult, reject) => {
    const repo = resolve(process.cwd(), "..");
    const python = process.env.REASONTRACE_PYTHON || resolve(repo, ".venv/bin/python");
    const child = spawn(python, ["-m", "credit_audit.reasontrace_demo"], {
      cwd: repo, stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, PYTHONUNBUFFERED: "1" },
    });
    let output = "";
    let error = "";
    let settled = false;
    const fail = (message: string) => { if (!settled) { settled = true; reject(new Error(message)); } };
    const timer = setTimeout(() => { child.kill("SIGKILL"); fail("Audit timed out"); }, 20_000);
    child.stdout.on("data", chunk => { output += chunk; if (output.length > 2_000_000) { child.kill("SIGKILL"); fail("Audit output exceeded limit"); } });
    child.stderr.on("data", chunk => { error += chunk; if (error.length > 20_000) { child.kill("SIGKILL"); fail("Audit error output exceeded limit"); } });
    child.on("error", cause => { clearTimeout(timer); fail(cause.message); });
    child.on("close", code => {
      clearTimeout(timer);
      if (settled) return;
      if (code !== 0) return fail(error || `Audit process exited ${code}`);
      try {
        const parsed = JSON.parse(output);
        if (!parsed || typeof parsed !== "object" || !Array.isArray(parsed.checks)) throw new Error("Invalid audit result");
        settled = true; resolveResult(parsed);
      } catch { fail("Audit returned invalid JSON"); }
    });
    child.stdin.end(JSON.stringify({ reviewed, agent, case_label: caseLabel, applicant_name: applicantName }));
  });
}
