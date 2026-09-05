"use client";

import { useState } from "react";
import Link from "next/link";
import { CaretDown, CaretRight } from "@phosphor-icons/react/dist/ssr";

import { StatusBadge } from "@/components/ui/status-badge";
import { formatMoneyShort } from "@/lib/format";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const STAGE_LABEL: Record<string, string> = {
  intake: "Intake",
  extraction: "Extraction",
  quote: "Quote",
  proposal: "Proposal",
};

function initials(brand: string): string {
  return brand
    .split(/\s+/)
    .map((word) => word[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function statusOf(project: Project): { label: string; variant: "progress" | "review" | "ok" | "neutral" } {
  if (project.activeJob) return { label: "Claude is reading", variant: "progress" };
  if (project.counts.needsLook > 0)
    return { label: `${project.counts.needsLook} to check`, variant: "review" };
  if (project.counts.total > 0) return { label: "All clear", variant: "ok" };
  return { label: "No lines yet", variant: "neutral" };
}

/**
 * The board, grouped by brand.
 *
 * Grouping happens here rather than in the API: a national-accounts desk runs
 * tens of live bids, not thousands, and a client-side group avoids a second
 * shape for the same data.
 */
export function BoardGroups({ projects }: { projects: Project[] }) {
  const groups = new Map<string, Project[]>();
  for (const project of projects) {
    const brand = project.brand?.trim() || "Unbranded";
    groups.set(brand, [...(groups.get(brand) ?? []), project]);
  }

  const [closed, setClosed] = useState<Set<string>>(new Set());

  if (projects.length === 0) {
    return (
      <div className="grid place-items-center gap-2 rounded-xl border border-subtle bg-panel px-6 py-16 text-center shadow-sm">
        <span className="text-[14px] font-semibold text-tx-primary">No bids here</span>
        <span className="max-w-[420px] text-[12.5px] text-tx-secondary">
          Create a bid, drop the plan set in, and the schedules are read for you.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {[...groups.entries()]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([brand, rows]) => {
          const open = !closed.has(brand);
          const value = rows.reduce((sum, row) => sum + (row.quoteTotal ?? 0), 0);
          const flags = rows.reduce((sum, row) => sum + row.counts.needsLook, 0);

          return (
            <div
              key={brand}
              className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm transition-colors hover:border-brand-border/50"
            >
              <button
                onClick={() =>
                  setClosed((current) => {
                    const next = new Set(current);
                    if (next.has(brand)) next.delete(brand);
                    else next.add(brand);
                    return next;
                  })
                }
                className={cn(
                  "flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-panel-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border",
                  open && "border-b border-subtle bg-panel-muted"
                )}
              >
                {open ? (
                  <CaretDown size={14} weight="bold" className="text-tx-muted" />
                ) : (
                  <CaretRight size={14} weight="bold" className="text-tx-muted" />
                )}
                <span className="grid h-8 w-8 place-items-center rounded-md bg-brand-soft text-[11px] font-bold text-brand-primary shadow-sm border border-brand-border/20">
                  {initials(brand)}
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="text-[14px] font-semibold text-tx-primary">{brand}</span>
                  <span className="text-[11.5px] font-medium text-tx-muted mt-0.5">
                    {rows.length} in this programme
                  </span>
                </span>

                <span className="flex-1" />

                {flags > 0 && (
                  <span className="rounded-full bg-status-error-soft px-2 py-0.5 text-[11px] font-semibold text-status-error shadow-sm border border-status-error/20">
                    {flags} flagged
                  </span>
                )}
                <span className="flex flex-col items-end leading-tight">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-tx-muted">
                    Programme value
                  </span>
                  <span className="tnum text-[14px] font-semibold text-tx-primary mt-0.5">
                    {value ? formatMoneyShort(value) : "—"}
                  </span>
                </span>
              </button>

              {open && (
                <div className="overflow-x-auto bg-background">
                  <div
                    className="grid min-w-[720px] gap-3 border-b border-subtle px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest text-tx-muted bg-panel/30"
                    style={{ gridTemplateColumns: "170px 1fr 110px 100px 90px 70px 110px" }}
                  >
                    <span>Bid</span>
                    <span>Customer</span>
                    <span>Due</span>
                    <span className="text-right">Value</span>
                    <span>Stage</span>
                    <span className="text-right">Ver.</span>
                    <span>Status</span>
                  </div>

                  {rows.map((project) => {
                    const status = statusOf(project);
                    return (
                      <Link
                        key={project.id}
                        href={`/bids/${project.code}/${project.stage}`}
                        className="group grid min-w-[720px] items-center gap-3 border-b border-subtle px-4 py-3 no-underline last:border-b-0 hover:bg-panel-muted transition-colors"
                        style={{ gridTemplateColumns: "170px 1fr 110px 100px 90px 70px 110px" }}
                      >
                        <span className="flex min-w-0 flex-col leading-tight">
                          <span className="tnum truncate text-[13px] font-semibold text-brand-primary transition-colors group-hover:text-brand-primary/80">
                            {project.code}
                          </span>
                          <span className="truncate text-[11px] font-medium text-tx-secondary mt-0.5">
                            {project.name}
                          </span>
                        </span>
                        <span className="truncate text-[13px] font-medium text-tx-secondary">
                          {project.gc ?? "—"}
                        </span>
                        <span className="tnum text-[12.5px] font-medium text-tx-muted">
                          {project.bidDue ? new Date(project.bidDue).toLocaleDateString() : "—"}
                        </span>
                        <span className="tnum text-right text-[13px] font-semibold text-tx-primary">
                          {project.quoteTotal ? formatMoneyShort(project.quoteTotal) : "—"}
                        </span>
                        <span className="text-[12.5px] font-medium text-tx-secondary">
                          {STAGE_LABEL[project.stage]}
                        </span>
                        <span className="tnum text-right text-[12.5px] font-medium text-tx-muted">
                          v{project.version ?? 1}
                        </span>
                        <span>
                          <StatusBadge variant={status.variant}>{status.label}</StatusBadge>
                        </span>
                      </Link>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
    </div>
  );
}
