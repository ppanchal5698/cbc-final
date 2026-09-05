import { PageHeader } from "@/components/shell/page-header";
import { DeadLetterQueue } from "@/components/jobs/dead-letter-queue";
import { api } from "@/lib/api";
import type { Job } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function DeadLetterPage() {
  const data = await api.get<{ jobs: Job[]; total: number }>("/api/jobs/dead");

  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace" }, { label: "Dead letter" }]} />
      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="mb-6">
          <h1 className="text-[26px] font-bold tracking-tight text-tx-primary">
            Dead letter
          </h1>
          <p className="mt-1.5 text-[14px] font-medium text-tx-secondary">
            {data.total} job{data.total === 1 ? "" : "s"} exhausted retries or failed
            permanently. Retry re-queues the same job for a worker.
          </p>
        </div>
        <DeadLetterQueue initialJobs={data.jobs} />
      </main>
    </>
  );
}
