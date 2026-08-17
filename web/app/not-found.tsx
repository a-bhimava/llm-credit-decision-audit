import Link from "next/link";
import { Shell } from "@/components/site";

export default function NotFound() {
  return (
    <Shell>
      <main className="notFound">
        <p className="eyebrow">404</p>
        <h1>This evidence record is not part of the published bundle.</h1>
        <Link href="/">Return to the current run</Link>
      </main>
    </Shell>
  );
}

