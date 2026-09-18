"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowBendDownLeft,
  CaretDown,
  CaretRight,
  Minus,
  PaperPlaneTilt,
  Paperclip,
  PencilSimple,
  Prohibit,
  Trophy,
  UploadSimple,
} from "@phosphor-icons/react/dist/ssr";

import {
  BID_STATUS_LABEL,
  OUTCOME_LABEL,
  bidStatusTone,
  nextOutcome,
  outcomeTone,
} from "@/components/bids/bid-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { daysUntil, dueLabel, estimatorLabel } from "@/lib/board";
import { formatMoneyShort } from "@/lib/format";
import { brandInitials } from "@/lib/initials";
import type { BidStatus, Outcome, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Column track, shared by the header and every row so they cannot drift.
 *
 * The prototype's ten columns, plus one: it never modelled background work, so
 * it has nowhere to say "Claude is reading" or "3 to check". Dropping that to
 * match the mock would lose a live signal, so Status stays.
 */
const COLUMNS =
  "minmax(180px,1.5fr) minmax(120px,0.9fr) 138px 126px 92px 130px 110px 92px 100px 56px 46px";

function statusOf(project: Project): { label: string; variant: "progress" | "review" | "ok" | "neutral" } {
  if (project.activeJob) return { label: "Claude is reading", variant: "progress" };
  const needsLook = project.counts?.needsLook ?? 0;
  const total = project.counts?.total ?? 0;
  if (needsLook > 0) return { label: `${needsLook} to check`, variant: "review" };
  if (total > 0) return { label: "All clear", variant: "ok" };
  return { label: "No lines yet", variant: "neutral" };
}

/** A chip that is also a control: one click records the next state. */
function Chip({
  label,
  icon,
  tone,
  title,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  tone: string;
  title: string;
  onClick?: (event: React.MouseEvent) => void;
}) {
  return (
    <button
      type="button"
      title={title}
      // A button's accessible name comes from its content, so without this a
      // screen reader announces the current state ("Open") and never what
      // pressing it would do. Both belong in the name.
      aria-label={label ? `${label} — ${title}` : title}
      disabled={!onClick}
      onClick={(event) => {
        // The whole row is a link to the bid; a chip is not.
        event.preventDefault();
        event.stopPropagation();
        onClick?.(event);
      }}
      className={cn(
        "flex w-full items-center justify-center gap-1 rounded-md border px-1.5 py-1 text-[11.5px] font-semibold transition-colors",
        tone,
        onClick ? "hover:brightness-125" : "cursor-default opacity-70",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

/**
 * The board, grouped by brand.
 *
 * Grouping happens here rather than in the API: a national-accounts desk runs
 * tens of live bids, not thousands, and a client-side group avoids a second
 * shape for the same data.
 *
 * The bid-status and outcome chips are controls, not labels - clicking one
 * records the next state, which is the only way either field is ever set.
 */
export function BoardGroups({
  projects,
  onSetBidStatus,
  onSetOutcome,
  onEdit,
  onPlans,
}: {
  projects: Project[];
  onSetBidStatus?: (project: Project, next: BidStatus) => void;
  onSetOutcome?: (project: Project, next: Outcome) => void;
  onEdit?: (project: Project) => void;
  onPlans?: (project: Project) => void;
}) {
  const groups = new Map<string, Project[]>();
  for (const project of projects) {
    const brand = project.brand?.trim() || "Unbranded";
    groups.set(brand, [...(groups.get(brand) ?? []), project]);
  }

  const [closed, setClosed] = useState<Set<string>>(new Set());

  if (projects.length === 0) {
    return (
      <div className="grid place-items-center gap-2 rounded-xl border border-subtle bg-panel px-6 py-16 text-center shadow-1">
        <span className="text-[14px] font-semibold text-tx-primary">No bids here</span>
        <span className="max-w-[420px] text-[12.5px] text-tx-secondary">
          Widen the status or pick a different estimator.
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
          const flags = rows.reduce((sum, row) => sum + (row.counts?.needsLook ?? 0), 0);
          const won = rows.filter((row) => row.outcome === "won").length;
          const lost = rows.filter((row) => row.outcome === "lost").length;
          const notBid = rows.filter((row) => row.bidStatus === "not_bid").length;

          return (
            <div
              key={brand}
              className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-1 transition-colors hover:border-brand-border/50"
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
                  open && "border-b border-subtle bg-panel-muted",
                )}
              >
                {open ? (
                  <CaretDown size={14} weight="bold" className="text-tx-muted" />
                ) : (
                  <CaretRight size={14} weight="bold" className="text-tx-muted" />
                )}
                <span className="grid h-8 w-8 place-items-center rounded-md border border-brand-border/20 bg-brand-soft text-[11px] font-bold text-brand-primary shadow-1">
                  {brandInitials(brand)}
                </span>
                <span className="flex flex-col leading-tight">
                  <span className="text-[14px] font-semibold text-tx-primary">{brand}</span>
                  <span className="mt-0.5 text-[11.5px] font-medium text-tx-muted">
                    {rows.length} bid{rows.length === 1 ? "" : "s"} · {won} won · {lost} lost ·{" "}
                    {notBid} not bid
                  </span>
                </span>

                <span className="flex-1" />

                <span
                  className={cn(
                    "rounded-full px-2 py-0.5 text-[11px] font-semibold shadow-1",
                    flags > 0
                      ? "border border-status-error/20 bg-status-error-soft text-status-error"
                      : "text-tx-muted",
                  )}
                >
                  {flags > 0 ? `${flags} flagged` : "No flags"}
                </span>
                <span className="flex flex-col items-end leading-tight">
                  <span className="text-[10px] font-bold uppercase tracking-widest text-tx-muted">
                    Programme value
                  </span>
                  <span className="tnum mt-0.5 text-[14px] font-semibold text-tx-primary">
                    {value ? formatMoneyShort(value) : "—"}
                  </span>
                </span>
              </button>

              {open && (
                <div className="overflow-x-auto bg-background">
                  <div
                    className="grid min-w-[1170px] gap-3 border-b border-subtle bg-panel/30 px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest text-tx-muted"
                    style={{ gridTemplateColumns: COLUMNS }}
                  >
                    <span>Bid</span>
                    <span>Customer</span>
                    <span>Entered by</span>
                    <span>Entered → due</span>
                    <span className="text-right">Value</span>
                    <span>Estimator</span>
                    <span>Status</span>
                    <span>Bid status</span>
                    <span>Outcome</span>
                    <span className="text-center">Plans</span>
                    <span className="text-center">Edit</span>
                  </div>

                  {rows.map((project) => {
                    const status = statusOf(project);
                    const bidStatus = project.bidStatus ?? "bid";
                    const outcome = project.outcome ?? "";
                    const days = daysUntil(project.bidDue);
                    const late = days !== null && days < 0 && !outcome && bidStatus === "bid";

                    return (
                      <Link
                        key={project.id}
                        href={`/bids/${project.code}/${project.stage}`}
                        className="group grid min-w-[1170px] items-center gap-3 border-b border-subtle px-4 py-3 no-underline transition-colors last:border-b-0 hover:bg-panel-muted"
                        style={{ gridTemplateColumns: COLUMNS }}
                      >
                        <span className="flex min-w-0 flex-col leading-tight">
                          <span className="tnum truncate text-[13px] font-semibold text-brand-primary transition-colors group-hover:text-brand-primary/80">
                            {project.code}
                          </span>
                          <span className="mt-0.5 truncate text-[11px] font-medium text-tx-secondary">
                            {project.name}
                          </span>
                        </span>

                        <span className="truncate text-[13px] font-medium text-tx-secondary">
                          {project.gc ?? "—"}
                        </span>

                        <span className="flex min-w-0 flex-col leading-tight">
                          <span className="truncate text-[12.5px] font-medium text-tx-primary">
                            {project.initiator || "—"}
                          </span>
                          <span className="truncate text-[11px] font-medium text-tx-muted">
                            {project.enteredByRole ?? "—"}
                          </span>
                        </span>

                        <span className="flex min-w-0 flex-col leading-tight">
                          <span
                            className={cn(
                              "tnum truncate text-[12.5px] font-medium",
                              late ? "text-status-error" : "text-tx-primary",
                            )}
                          >
                            {project.bidDue
                              ? `due ${new Date(project.bidDue).toLocaleDateString()}`
                              : "no due date"}
                          </span>
                          <span className="truncate text-[11px] font-medium text-tx-muted">
                            {dueLabel(days)}
                          </span>
                        </span>

                        <span className="tnum text-right text-[13px] font-semibold text-tx-primary">
                          {project.quoteTotal ? formatMoneyShort(project.quoteTotal) : "—"}
                        </span>

                        <span className="flex min-w-0 items-center gap-2">
                          <span
                            className={cn(
                              "grid h-6 w-6 shrink-0 place-items-center rounded-full text-[10px] font-bold",
                              project.estimator
                                ? "bg-panel-muted text-tx-secondary"
                                : "text-tx-muted",
                            )}
                          >
                            {project.estimator?.initials || "—"}
                          </span>
                          <span className="truncate text-[12px] font-medium text-tx-secondary">
                            {estimatorLabel(project)}
                          </span>
                        </span>

                        <span className="min-w-0">
                          <StatusBadge variant={status.variant}>{status.label}</StatusBadge>
                        </span>

                        <Chip
                          label={BID_STATUS_LABEL[bidStatus]}
                          tone={bidStatusTone(bidStatus)}
                          title={
                            bidStatus === "bid" ? "Click to mark Not bid" : "Click to mark Bid"
                          }
                          icon={
                            bidStatus === "bid" ? (
                              <PaperPlaneTilt size={12} weight="duotone" />
                            ) : (
                              <Prohibit size={12} weight="duotone" />
                            )
                          }
                          onClick={
                            onSetBidStatus
                              ? () =>
                                  onSetBidStatus(project, bidStatus === "bid" ? "not_bid" : "bid")
                              : undefined
                          }
                        />

                        <Chip
                          label={bidStatus === "not_bid" ? "No outcome" : OUTCOME_LABEL[outcome]}
                          tone={outcomeTone(outcome)}
                          title={
                            bidStatus === "not_bid"
                              ? "Not bid — no outcome applies"
                              : outcome === ""
                                ? "Click to mark Won"
                                : outcome === "won"
                                  ? "Click to mark Lost"
                                  : "Click to reopen"
                          }
                          icon={
                            outcome === "won" ? (
                              <Trophy size={12} weight="duotone" />
                            ) : outcome === "lost" ? (
                              <ArrowBendDownLeft size={12} weight="duotone" />
                            ) : (
                              <Minus size={12} weight="bold" />
                            )
                          }
                          onClick={
                            onSetOutcome && bidStatus !== "not_bid"
                              ? () => onSetOutcome(project, nextOutcome(outcome))
                              : undefined
                          }
                        />

                        <span className="grid place-items-center">
                          <Chip
                            label={project.documentCount ? String(project.documentCount) : "Add"}
                            tone={
                              project.documentCount
                                ? "border-brand-border bg-brand-soft text-brand-primary"
                                : "border-subtle bg-transparent text-tx-muted"
                            }
                            title="Plans on this bid"
                            icon={
                              project.documentCount ? (
                                <Paperclip size={12} weight="duotone" />
                              ) : (
                                <UploadSimple size={12} weight="duotone" />
                              )
                            }
                            onClick={onPlans ? () => onPlans(project) : undefined}
                          />
                        </span>

                        <span className="grid place-items-center">
                          <Chip
                            label=""
                            tone="border-subtle bg-transparent text-tx-muted"
                            title="Update owner, dates and outcome"
                            icon={<PencilSimple size={13} weight="duotone" />}
                            onClick={onEdit ? () => onEdit(project) : undefined}
                          />
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
