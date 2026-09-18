import Link from "next/link";
import { ListChecks, CaretRight, Buildings, FileText, Table, Tray } from "@phosphor-icons/react/dist/ssr";

import { auth } from "@/auth";
import { PageHeader } from "@/components/shell/page-header";
import { NewBidDialog } from "@/components/bids/new-bid-dialog";
import {
  BidToOrder,
  DueNext,
  EstimatorLoad,
  Panel,
  PipelineByStage,
  ValueByProgramme,
  WonLostNotBid,
} from "@/components/dashboard/panels";
import { StatusBadge, type StatusBadgeVariant } from "@/components/ui/status-badge";
import { api } from "@/lib/api";
import { formatMoneyShort } from "@/lib/format";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

const STAGE_ICON = {
  intake: Tray,
  extraction: ListChecks,
  quote: Table,
  proposal: FileText,
} as const;

function greeting(name?: string | null): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Morning" : hour < 18 ? "Afternoon" : "Evening";
  const first = String(name ?? "there").trim().split(/\s+/)[0] || "there";
  return `${part}, ${first}`;
}

/** What this bid is actually waiting on, in the estimator's words. */
function waitingOn(project: Project): { tag: string; colourClass: string; softClass: string; variant: StatusBadgeVariant } {
  const blocked = new Set([
    "extraction_needs_review",
    "pricing_failed",
    "quoting_failed",
    "awaiting_manual_retry",
    "dead",
  ]);
  if (project.chainState && blocked.has(project.chainState))
    return { tag: "Needs attention", colourClass: "text-status-error", softClass: "bg-status-error-soft", variant: "review" };
  if (project.activeJob)
    return { tag: "Claude is reading", colourClass: "text-status-warning", softClass: "bg-status-warning-soft", variant: "progress" };
  if (project.counts.needsLook > 0)
    return {
      tag: `${project.counts.needsLook} to check`,
      colourClass: "text-status-error",
      softClass: "bg-status-error-soft",
      variant: "review",
    };
  if (project.documentCount === 0)
    return { tag: "Needs documents", colourClass: "text-tx-muted", softClass: "bg-panel-muted", variant: "neutral" };
  if (project.stage === "proposal")
    return { tag: "Ready to hand off", colourClass: "text-status-success", softClass: "bg-status-success-soft", variant: "ok" };
  return { tag: "Ready to price", colourClass: "text-brand-primary", softClass: "bg-brand-soft", variant: "action" };
}

export default async function DashboardPage() {
  const session = await auth();
  const name = session?.user?.name ?? "Estimator";

  // Not caught here. A dead API used to render as "0 open bids · nothing is
  // flagged", which reads as a calm empty desk rather than a broken one; the
  // error boundary in app/(app)/error.tsx says what actually happened.
  const projects = (await api.get<{ projects: Project[] }>("/api/projects")).projects;

  const needsLook = projects.reduce((sum, project) => sum + project.counts.needsLook, 0);

  // Most urgent first: flagged work, then anything Claude is mid-way through.
  const queue = [...projects].sort((a, b) => {
    const score = (p: Project) => (p.counts.needsLook > 0 ? 0 : p.activeJob ? 1 : 2);
    return score(a) - score(b);
  });

  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace" }, { label: "Dashboard" }]} reviewCount={needsLook} />

      <main id="main-content" className="min-h-0 flex-1 overflow-auto bg-background p-8">
        <div className="mb-7 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-[30px] font-extrabold tracking-tight text-tx-primary">
              {greeting(name)} <span className="animate-fade-in">👋</span>
            </h1>
            <p className="mt-1 max-w-[640px] text-[14px] font-medium leading-relaxed text-tx-secondary">
              {needsLook > 0
                ? `${needsLook} line${needsLook === 1 ? "" : "s"} are waiting on you across ${projects.length} bid${projects.length === 1 ? "" : "s"}.`
                : "Nothing is flagged. Bid documents in, priced proposal out."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="hidden items-center gap-3 rounded-lg border border-subtle bg-panel px-4 py-2 shadow-1 sm:flex">
              <Buildings size={18} weight="duotone" className="text-tx-muted" />
              <span className="flex flex-col leading-tight">
                <span className="text-[10px] font-bold uppercase tracking-widest text-tx-muted">
                  Current workspace
                </span>
                <span className="text-[13px] font-semibold text-tx-primary">Hamilton Parker · CBC</span>
              </span>
            </div>
            <NewBidDialog />
          </div>
        </div>

        {/* The prototype's two rows: the pipeline and its outcomes, then the
            queue beside the four roll-ups that explain it. */}
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <PipelineByStage projects={projects} />
          <WonLostNotBid projects={projects} />
        </div>

        <div className="mt-5 grid items-start gap-5 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <Panel
            title="Your queue"
            icon={<ListChecks size={17} weight="duotone" />}
            action={
              <Link
                href="/bids"
                className="text-[13px] font-medium text-brand-primary no-underline transition-colors hover:text-brand-primary/80"
              >
                Open the bid board &rarr;
              </Link>
            }
          >
            {queue.length === 0 ? (
              <div className="grid place-items-center gap-3 px-6 py-24 text-center">
                <div className="mb-2 flex h-16 w-16 items-center justify-center rounded-full border border-brand-border bg-brand-soft shadow-1">
                  <Tray size={28} weight="duotone" className="text-brand-primary" />
                </div>
                <span className="text-[16px] font-semibold text-tx-primary">Nothing in the queue</span>
                <span className="max-w-[380px] text-[13.5px] leading-relaxed text-tx-secondary">
                  Create a bid and drop the plan set in to get started. Everything is clear for now.
                </span>
              </div>
            ) : (
              <div className="max-h-[420px] overflow-auto">
                {queue.map((project) => {
                  const Icon = STAGE_ICON[project.stage];
                  const state = waitingOn(project);
                  return (
                    <Link
                      key={project.id}
                      href={`/bids/${project.code}/${project.stage}`}
                      className="group grid items-center gap-3 border-b border-subtle px-5 py-3 no-underline transition-colors last:border-b-0 hover:bg-panel-muted"
                      style={{ gridTemplateColumns: "34px minmax(0,1fr) 104px 88px 20px" }}
                    >
                      <span
                        className={cn(
                          "grid h-[34px] w-[34px] shrink-0 place-items-center rounded-lg border border-subtle/50 shadow-1",
                          state.softClass,
                          state.colourClass,
                        )}
                      >
                        <Icon size={17} weight="duotone" />
                      </span>
                      <span className="flex min-w-0 flex-col leading-tight">
                        <span className="truncate text-[13.5px] font-semibold text-tx-primary transition-colors group-hover:text-brand-primary">
                          {project.name}
                        </span>
                        <span className="mt-0.5 truncate text-[11.5px] font-medium text-tx-muted">
                          {project.code}
                          {project.gc ? ` · ${project.gc}` : ""}
                          {project.location ? ` · ${project.location}` : ""}
                        </span>
                      </span>
                      <StatusBadge variant={state.variant}>{state.tag}</StatusBadge>
                      <span className="tnum text-right text-[12px] font-medium text-tx-muted">
                        {project.bidDue
                          ? `due ${new Date(project.bidDue).toLocaleDateString()}`
                          : formatMoneyShort(project.quoteTotal)}
                      </span>
                      <CaretRight
                        size={14}
                        weight="bold"
                        className="text-tx-muted transition-colors group-hover:text-tx-primary"
                      />
                    </Link>
                  );
                })}
              </div>
            )}
          </Panel>

          <div className="flex min-w-0 flex-col gap-5">
            <DueNext projects={projects} />
            <EstimatorLoad projects={projects} />
            <BidToOrder projects={projects} />
            <ValueByProgramme projects={projects} />
          </div>
        </div>
      </main>
    </>
  );
}
