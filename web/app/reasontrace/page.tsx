import { ProductShell } from "@/components/product-shell";
import { ReasonTrace } from "@/components/reasontrace";
import { ReasonTraceLogin } from "@/components/reasontrace-login";
import { createClient } from "@/lib/supabase/server";
import { localFixturesEnabled } from "@/lib/reasontrace/local-mode";
import "./reasontrace.css";

export const metadata = {
  title: "ReasonTrace — source to reason",
  description: "A synthetic credit-decision QA case connecting document evidence to causal reason tests.",
};

export const dynamic = "force-dynamic";

export default async function ReasonTracePage() {
  if (localFixturesEnabled()) return <ProductShell><ReasonTrace localFixtures /></ProductShell>;
  const supabase = await createClient();
  const { data } = await supabase.auth.getClaims();
  return <ProductShell>{data?.claims.sub ? <ReasonTrace /> : <ReasonTraceLogin />}</ProductShell>;
}
