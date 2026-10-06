import Link from "next/link";
import { ProductNavigation } from "@/components/product-navigation";

export function ProductShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="productShell">
      <header className="productHeader">
        <Link className="productMark" href="/" aria-label="Credit Decision Audit home">
          <span className="productMarkDot" aria-hidden="true" />
          <span>causal audit infrastructure</span>
        </Link>
        <ProductNavigation />
      </header>
      {children}
      <footer className="productFooter">
        <span>Fictional applications only. Not lending, credit, legal, or compliance advice.</span>
        <Link href="/evidence">Inspect the published evidence</Link>
      </footer>
    </div>
  );
}
