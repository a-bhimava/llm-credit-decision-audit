import { RunOverview } from "@/components/overview";
import { getRun, loadRunIndex } from "@/lib/evidence";

export const dynamic = "force-static";

export default async function HomePage() {
  const index = await loadRunIndex();
  return <RunOverview run={await getRun(index.default_run_id)} />;
}

