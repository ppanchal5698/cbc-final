import { PageHeader } from "@/components/shell/page-header";
import { SpendOpsPanel } from "@/components/ops/spend-ops-panel";

export const dynamic = "force-dynamic";

export default function SpendOpsPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace" }, { label: "Spend" }]} />
      <main id="main-content" className="min-h-0 flex-1 overflow-auto bg-background p-8">
        <div className="mb-6">
          <h1 className="text-[26px] font-bold tracking-tight text-tx-primary">Spend</h1>
          <p className="mt-1.5 text-[14px] font-medium text-tx-secondary">
            LLM cost from `runMetrics` versus worker claim caps. Requires an admin
            session.
          </p>
        </div>
        <SpendOpsPanel />
      </main>
    </>
  );
}
