import Link from "next/link";

export function ProductShell({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <div className="productShell">
      <header className="productHeader">
        <Link className="productMark" href="/" aria-label="Credit Decision Audit home">
          <span className="productMarkDot" aria-hidden="true" />
          <span>credit decision audit</span>
        </Link>
        <nav aria-label="Product navigation">
          <Link href="/audit">Audit studio</Link>
          <Link href="/evidence">Evidence ledger</Link>
        </nav>
      </header>
      {children}
      <footer className="productFooter">
        <span>Fictional applications only. Not lending, credit, legal, or compliance advice.</span>
        <Link href="/evidence">Inspect the published evidence</Link>
      </footer>
    </div>
  );
}
