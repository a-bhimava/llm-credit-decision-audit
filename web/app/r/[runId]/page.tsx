import type { Metadata } from "next";
import { RunOverview } from "@/components/overview";
import { getRun, loadRunIndex } from "@/lib/evidence";

export const dynamic = "force-static";
export const dynamicParams = false;

type Props = { params: Promise<{ runId: string }> };

export async function generateStaticParams() {
  return (await loadRunIndex()).runs.map((run) => ({ runId: run.run_id }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { runId } = await params;
  const run = await getRun(runId);
  return { title: run.label };
}

export default async function RunPage({ params }: Props) {
  const { runId } = await params;
  return <RunOverview run={await getRun(runId)} />;
}

