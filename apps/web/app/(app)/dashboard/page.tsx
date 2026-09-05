import Link from "next/link";
import {
  ListChecks,
  CaretRight,
  Buildings,
  Timer,
  WarningCircle,
  Lightning,
  FileText,
  Table,
  Tray,
} from "@phosphor-icons/react/dist/ssr";

import { auth } from "@/auth";
import { PageHeader } from "@/components/shell/page-header";
import { NewBidDialog } from "@/components/bids/new-bid-dialog";
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

function greeting(name: string): string {
  const hour = new Date().getHours();
  const part = hour < 12 ? "Morning" : hour < 18 ? "Afternoon" : "Evening";
  return `${part}, ${name.split(" ")[0]}`;
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
  const running = projects.filter((project) => project.activeJob).length;
  const openValue = projects.reduce((sum, project) => sum + (project.quoteTotal ?? 0), 0);
  const handedOff = projects.filter((project) => project.handedOffTo).length;

  // Most urgent first: flagged work, then anything Claude is mid-way through.
  const queue = [...projects].sort((a, b) => {
    const score = (p: Project) => (p.counts.needsLook > 0 ? 0 : p.activeJob ? 1 : 2);
    return score(a) - score(b);
  });

  const cleared = projects.reduce((sum, p) => sum + p.counts.clear, 0);
  const total = projects.reduce((sum, p) => sum + p.counts.total, 0);
  const focusPct = total ? Math.round((cleared / total) * 100) : 0;

  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace" }, { label: "Dashboard" }]} reviewCount={needsLook} />

      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="flex items-center gap-2 text-[26px] font-bold text-tx-primary tracking-tight">
              {greeting(name)} <span className="animate-fade-in">👋</span>
            </h1>
            <p className="mt-1.5 text-[14px] text-tx-secondary font-medium max-w-[600px] leading-relaxed">
              {needsLook > 0
                ? `${needsLook} line${needsLook === 1 ? "" : "s"} are waiting on you across ${projects.length} bid${projects.length === 1 ? "" : "s"}.`
                : "Nothing is flagged. Bid documents in, priced proposal out."}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="hidden items-center gap-3 rounded-lg border border-subtle bg-panel px-4 py-2 sm:flex shadow-sm">
              <Buildings size={18} weight="duotone" className="text-tx-muted" />
              <span className="flex flex-col leading-tight">
                <span className="text-[10px] uppercase tracking-widest text-tx-muted font-bold">
                  Current workspace
                </span>
                <span className="text-[13px] font-semibold text-tx-primary">Hamilton Parker · CBC</span>
              </span>
            </div>
            <NewBidDialog />
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
          <section className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm flex flex-col">
            <div className="flex items-center gap-3 border-b border-subtle px-5 py-4 bg-background">
              <ListChecks size={18} weight="duotone" className="text-brand-primary" />
              <span className="text-[15px] font-semibold text-tx-primary tracking-tight">Your queue</span>
              <span className="flex-1" />
              <Link
                href="/bids"
                className="text-[13px] font-medium text-brand-primary no-underline hover:text-brand-primary/80 transition-colors"
              >
                Open the bid board &rarr;
              </Link>
            </div>

            {queue.length === 0 ? (
              <div className="grid place-items-center gap-3 px-6 py-24 text-center">
                <div className="w-16 h-16 rounded-full bg-brand-soft flex items-center justify-center mb-2 shadow-sm border border-brand-border">
                  <Tray size={28} weight="duotone" className="text-brand-primary" />
                </div>
                <span className="text-[16px] font-semibold text-tx-primary">Nothing in the queue</span>
                <span className="max-w-[380px] text-[13.5px] text-tx-secondary leading-relaxed">
                  Create a bid and drop the plan set in to get started. Everything is clear for now.
                </span>
              </div>
            ) : (
              <div className="flex-1 overflow-auto">
                {queue.map((project) => {
                  const Icon = STAGE_ICON[project.stage];
                  const state = waitingOn(project);
                  return (
                    <Link
                      key={project.id}
                      href={`/bids/${project.code}/${project.stage}`}
                      className="group flex items-center gap-4 border-b border-subtle px-5 py-3.5 no-underline last:border-b-0 hover:bg-panel-muted transition-colors"
                    >
                      <span className={cn("grid h-9 w-9 shrink-0 place-items-center rounded-lg shadow-sm border border-subtle/50", state.softClass, state.colourClass)}>
                        <Icon size={18} weight="duotone" />
                      </span>
                      <span className="flex min-w-0 flex-1 flex-col leading-tight">
                        <span className="truncate text-[14px] font-semibold text-tx-primary group-hover:text-brand-primary transition-colors">{project.name}</span>
                        <span className="truncate text-[12px] font-medium text-tx-muted mt-0.5">
                          {project.code}
                          {project.gc ? ` · ${project.gc}` : ""}
                          {project.location ? ` · ${project.location}` : ""}
                        </span>
                      </span>
                      <StatusBadge variant={state.variant}>{state.tag}</StatusBadge>
                      <span className="tnum hidden w-[92px] shrink-0 text-right text-[12px] font-medium text-tx-muted sm:block">
                        {project.bidDue
                          ? `due ${new Date(project.bidDue).toLocaleDateString()}`
                          : "no due date"}
                      </span>
                      <CaretRight size={14} weight="bold" className="text-tx-muted group-hover:text-tx-primary transition-colors ml-2" />
                    </Link>
                  );
                })}
              </div>
            )}
          </section>

          <aside className="flex flex-col gap-6">
            <div className="rounded-xl border border-subtle bg-panel p-5 shadow-sm">
              <div className="flex items-center gap-2 mb-6">
                <Timer size={16} weight="duotone" className="text-brand-primary" />
                <span className="text-[14px] font-semibold text-tx-primary tracking-tight">Focus</span>
              </div>

              <div className="grid place-items-center relative">
                <div
                  className="grid h-[120px] w-[120px] place-items-center rounded-full shadow-sm"
                  style={{
                    background: `conic-gradient(var(--brand-primary) ${focusPct * 3.6}deg, var(--panel-muted) 0deg)`,
                  }}
                >
                  <div className="grid h-[92px] w-[92px] place-items-center rounded-full bg-panel shadow-sm">
                    <span className="flex flex-col items-center leading-tight">
                      <span className="tnum text-[26px] font-bold text-tx-primary">{focusPct}%</span>
                      <span className="text-[11px] font-medium text-tx-muted mt-0.5 uppercase tracking-wider">
                        cleared
                      </span>
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-6 text-center">
                <p className="text-[14px] font-semibold text-tx-primary">
                  {needsLook > 0 ? `${needsLook} still need a look` : "Everything is checked"}
                </p>
                <p className="mt-1 text-[12.5px] font-medium text-tx-secondary leading-relaxed">
                  {cleared} of {total} extracted lines confirmed across every open bid.
                </p>
              </div>
            </div>

            <div className="rounded-xl border border-subtle bg-panel p-5 shadow-sm">
              <div className="mb-4">
                <span className="text-[14px] font-semibold text-tx-primary tracking-tight">Overview</span>
              </div>
              <div className="flex flex-col gap-1">
                {[
                  { label: "Open bids", value: String(projects.length), Icon: Buildings },
                  {
                    label: "Claude running",
                    value: String(running),
                    Icon: Lightning,
                    toneClass: running ? "text-status-warning" : "text-tx-primary",
                  },
                  {
                    label: "Lines to check",
                    value: String(needsLook),
                    Icon: WarningCircle,
                    toneClass: needsLook ? "text-status-error" : "text-tx-primary",
                  },
                  { label: "Handed to sales", value: String(handedOff), Icon: FileText, toneClass: "text-tx-primary" },
                  { label: "Quoted value", value: formatMoneyShort(openValue), Icon: Table, toneClass: "text-brand-primary" },
                ].map((tile) => (
                  <div
                    key={tile.label}
                    className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-panel-muted transition-colors"
                  >
                    <div className="flex h-7 w-7 items-center justify-center rounded-md border border-subtle bg-background shadow-sm">
                      <tile.Icon size={14} weight="duotone" className="text-tx-muted" />
                    </div>
                    <span className="flex-1 text-[13px] font-medium text-tx-secondary">
                      {tile.label}
                    </span>
                    <span className={cn("tnum text-[14px] font-bold", tile.toneClass || "text-tx-primary")}>
                      {tile.value}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </aside>
        </div>
      </main>
    </>
  );
}
