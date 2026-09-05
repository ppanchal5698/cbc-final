"use client";

import Link from "next/link";
import { CheckSquare, ListChecks, Table, FileText } from "@phosphor-icons/react/dist/ssr";

import { formatMoneyShort } from "@/lib/format";
import type { Project, Stage } from "@/lib/types";

const STAGES: { key: Stage; label: string; Icon: typeof CheckSquare }[] = [
  { key: "intake", label: "Intake", Icon: CheckSquare },
  { key: "extraction", label: "Extraction & entry", Icon: ListChecks },
  { key: "quote", label: "Quote", Icon: Table },
  { key: "proposal", label: "Proposal", Icon: FileText },
];

const ORDER: Stage[] = ["intake", "extraction", "quote", "proposal"];

export function StageBar({ project, current }: { project: Project; current: Stage }) {
  const currentIndex = ORDER.indexOf(current);

  function subtitle(stage: Stage): string {
    switch (stage) {
      case "intake":
        return `${project.documentCount} document${project.documentCount === 1 ? "" : "s"}`;
      case "extraction":
        return project.counts.total
          ? `${project.counts.needsLook} to check`
          : "not read yet";
      case "quote":
        return project.quoteTotal ? formatMoneyShort(project.quoteTotal) : "not priced";
      case "proposal":
        return project.stage === "proposal" ? "Draft" : "—";
    }
  }

  return (
    <div className="flex shrink-0 items-center gap-4 border-b border-subtle bg-background px-5 py-3">
      <span className="flex w-[230px] shrink-0 flex-col leading-tight">
        <span className="truncate text-[14px] font-bold tracking-tight text-tx-primary" title={project.name}>
          {project.name}
        </span>
        <span className="text-[12px] font-medium text-tx-muted mt-0.5">
          {project.code}
          {project.projectNumber ? ` / ${project.projectNumber}` : ""}
          {project.bidDue ? ` · bid due ${new Date(project.bidDue).toLocaleDateString()}` : ""}
        </span>
      </span>

      <span className="flex flex-1 items-center gap-3">
        {STAGES.map(({ key, label, Icon }, index) => {
          const active = key === current;
          const done = index < currentIndex;
          return (
            <Link
              key={key}
              href={`/bids/${project.code}/${key}`}
              className={`flex flex-1 items-center gap-3 rounded-xl px-4 py-2.5 no-underline transition-all shadow-sm ${
                active 
                  ? "bg-brand-primary/10 border border-brand-primary/20" 
                  : "bg-panel border border-subtle hover:bg-panel-muted hover:border-brand-border"
              }`}
            >
              <span
                className={`grid h-[28px] w-[28px] shrink-0 place-items-center rounded-lg shadow-sm ${
                  done 
                    ? "bg-status-success-soft text-status-success border border-status-success/20" 
                    : active 
                      ? "bg-brand-primary text-white border border-brand-primary/20" 
                      : "bg-panel-muted text-tx-muted border border-subtle"
                }`}
              >
                <Icon size={16} weight={active || done ? "fill" : "duotone"} />
              </span>
              <span className="flex min-w-0 flex-col leading-tight">
                <span className={`truncate text-[13px] font-bold ${active ? "text-brand-primary" : "text-tx-primary"}`}>
                  {label}
                </span>
                <span className="truncate text-[11px] font-medium text-tx-muted mt-0.5">
                  {subtitle(key)}
                </span>
              </span>
            </Link>
          );
        })}
      </span>

      <span className="flex w-[150px] shrink-0 flex-col items-end gap-1.5">
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          Bid progress
        </span>
        <span className="flex w-full items-center gap-3">
          <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-panel-muted border border-subtle shadow-inner">
            <span
              className="block h-full rounded-full bg-brand-primary transition-all duration-500 ease-out"
              style={{ width: `${project.progress}%` }}
            />
          </span>
          <span className="tnum text-[12.5px] font-bold text-tx-primary">{project.progress}%</span>
        </span>
      </span>
    </div>
  );
}
