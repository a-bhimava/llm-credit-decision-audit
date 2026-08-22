import type { NextConfig } from "next";
import { withWorkflow } from "workflow/next";
import path from "path";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Pin Vercel's output file tracer to the monorepo root so it doesn't get
  // confused by the presence of both pnpm-lock.yaml (web/) and
  // package-lock.json (repo root), which would cause ENOENT errors at runtime
  // or accidentally bundle the entire monorepo.
  outputFileTracingRoot: path.join(__dirname, "../"),
};

export default withWorkflow(nextConfig);
