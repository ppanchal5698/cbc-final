import { auth } from "@/auth";
import { PageHeader } from "@/components/shell/page-header";
import { BidBoard } from "@/components/bids/bid-board";
import { BidBoardSearch } from "@/components/bids/bid-board-search";
import { NewBidDialog } from "@/components/bids/new-bid-dialog";
import { api } from "@/lib/api";
import { formatMoneyShort } from "@/lib/format";
import { sumValue } from "@/lib/board";
import type { Project } from "@/lib/types";
import { Tray } from "@phosphor-icons/react/dist/ssr";

export const dynamic = "force-dynamic";

export default async function BidBoardPage({
  searchParams,
}: {
  searchParams: Promise<{ stage?: string; q?: string }>;
}) {
  const { stage, q } = await searchParams;
  const session = await auth();

  const query = new URLSearchParams();
  // `stage` is still honoured so an existing link keeps working; the board's
  // own filters are status-shaped and live on the client.
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

      <main id="main-content" className="min-h-0 flex-1 overflow-auto bg-background p-8">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-bold tracking-tight text-tx-primary">Bid board</h1>
            <p className="mt-1.5 text-[14px] font-medium text-tx-secondary">
              {projects.length} bid{projects.length === 1 ? "" : "s"} ·{" "}
              {formatMoneyShort(sumValue(projects))} quoted value · grouped by brand
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <BidBoardSearch key={q ?? ""} stage={stage} initialQuery={q ?? ""} />
            <NewBidDialog />
          </div>
        </div>

        {projects.length === 0 ? (
          <div className="grid place-items-center gap-3 rounded-xl border border-subtle bg-panel px-6 py-24 text-center shadow-1">
            <div className="mb-2 flex h-16 w-16 items-center justify-center rounded-full border border-brand-border bg-brand-soft shadow-1">
              <Tray size={28} weight="duotone" className="text-brand-primary" />
            </div>
            <span className="text-[16px] font-semibold text-tx-primary">
              {q ? "No bids match that search" : "No bids yet"}
            </span>
            <span className="max-w-[420px] text-[13.5px] leading-relaxed text-tx-secondary">
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
          <BidBoard projects={projects} me={session?.user?.email ?? ""} />
        )}
      </main>
    </>
  );
}
