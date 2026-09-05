import Link from "next/link";

import { PageHeader } from "@/components/shell/page-header";
import { BoardGroups } from "@/components/bids/board-groups";
import { BidBoardSearch } from "@/components/bids/bid-board-search";
import { NewBidDialog } from "@/components/bids/new-bid-dialog";
import { api } from "@/lib/api";
import type { Project, Stage } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Tray } from "@phosphor-icons/react/dist/ssr";

export const dynamic = "force-dynamic";

const FILTERS: { key: Stage | "all"; label: string }[] = [
  { key: "all", label: "All" },
  { key: "intake", label: "Intake" },
  { key: "extraction", label: "Extraction" },
  { key: "quote", label: "Quote" },
  { key: "proposal", label: "Proposal" },
];

export default async function BidBoardPage({
  searchParams,
}: {
  searchParams: Promise<{ stage?: string; q?: string }>;
}) {
  const { stage, q } = await searchParams;

  const query = new URLSearchParams();
  if (stage && stage !== "all") query.set("stage", stage);
  if (q) query.set("q", q);

  // See the dashboard: an unreachable API is reported by the error boundary,
  // not disguised as an empty board.
  const projects = (
    await api.get<{ projects: Project[] }>(`/api/projects?${query.toString()}`)
  ).projects;

  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace" }, { label: "Bid board" }]} />

      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-bold text-tx-primary tracking-tight">Bid board</h1>
            <p className="mt-1.5 text-[14px] text-tx-secondary font-medium">
              {projects.length} bid{projects.length === 1 ? "" : "s"} · grouped by brand
              {stage && stage !== "all" ? ` in ${stage}` : ""}
            </p>
          </div>
          <NewBidDialog />
        </div>

        <div className="mb-6 flex gap-2">
          {FILTERS.map((filter) => {
            const active = (stage ?? "all") === filter.key;
            return (
              <Link
                key={filter.key}
                href={`/bids?stage=${filter.key}${q ? `&q=${encodeURIComponent(q)}` : ""}`}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-md px-3.5 py-1.5 text-[13px] font-medium no-underline transition-colors shadow-sm",
                  active
                    ? "bg-brand-soft border border-brand-border text-brand-primary"
                    : "bg-panel border border-subtle text-tx-secondary hover:text-tx-primary hover:bg-panel-muted"
                )}
              >
                {filter.label}
              </Link>
            );
          })}
        </div>

        <div className="mb-6 flex flex-wrap items-center gap-3">
          <BidBoardSearch key={q ?? ""} stage={stage} initialQuery={q ?? ""} />
        </div>

        {projects.length === 0 ? (
          <div className="grid place-items-center gap-3 rounded-xl bg-panel border border-subtle px-6 py-24 text-center shadow-sm">
            <div className="w-16 h-16 rounded-full bg-brand-soft flex items-center justify-center mb-2 shadow-sm border border-brand-border">
              <Tray size={28} weight="duotone" className="text-brand-primary" />
            </div>
            <span className="text-[16px] font-semibold text-tx-primary">
              {q ? "No bids match that search" : "No bids yet"}
            </span>
            <span className="max-w-[420px] text-[13.5px] text-tx-secondary leading-relaxed">
              {q
                ? "Try a different code, name, or brand — or clear the search to see all bids."
                : "Create a bid to start intake. Upload a plan set and Claude reads the openings for you."}
            </span>
            {!q && (
              <div className="mt-4">
                <NewBidDialog />
              </div>
            )}
          </div>
        ) : (
          <BoardGroups projects={projects} />
        )}
      </main>
    </>
  );
}
