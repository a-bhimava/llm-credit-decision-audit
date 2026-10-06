"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const sections = [
  { suffix: "", label: "Overview" },
  { suffix: "/checks", label: "Checks" },
  { suffix: "/defects", label: "Validation" },
  { suffix: "/integrity", label: "Integrity" },
  { suffix: "/methods", label: "Methods" },
] as const;

export function RunNavigation({ runId }: { runId: string }) {
  const pathname = usePathname();
  const base = `/r/${encodeURIComponent(runId)}`;
  function isCurrent(suffix: typeof sections[number]["suffix"]) {
    if (!suffix) return pathname === "/evidence" || pathname === base;
    if (suffix === "/checks") return pathname.startsWith(`${base}/checks`) || pathname.startsWith(`${base}/pairs`);
    return pathname === `${base}${suffix}`;
  }

  return <nav className="runNav" aria-label="Run navigation">
    {sections.map(({ suffix, label }) => <Link key={label} href={`${base}${suffix}`}
      aria-current={isCurrent(suffix) ? "page" : undefined}>{label}</Link>)}
  </nav>;
}
