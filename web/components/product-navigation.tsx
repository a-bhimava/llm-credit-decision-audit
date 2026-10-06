"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const destinations = [
  { href: "/reasontrace", label: "ReasonTrace", shortLabel: "ReasonTrace" },
  { href: "/audit", label: "Audit studio", shortLabel: "Audit" },
  { href: "/evidence", label: "Evidence ledger", shortLabel: "Evidence" },
] as const;

export function ProductNavigation() {
  const pathname = usePathname();
  return <nav aria-label="Product navigation">
    {destinations.map(({ href, label, shortLabel }) => <Link key={href} href={href}
      aria-label={label}
      aria-current={pathname === href || pathname.startsWith(`${href}/`) ? "page" : undefined}>
      <span className="productNavLong" aria-hidden="true">{label}</span>
      <span className="productNavShort" aria-hidden="true">{shortLabel}</span>
    </Link>)}
  </nav>;
}
