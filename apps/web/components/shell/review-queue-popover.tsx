"use client";

import { useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { Bell, CaretRight } from "@phosphor-icons/react/dist/ssr";

import {
  Popover,
  PopoverContent,
  PopoverHeader,
  PopoverTitle,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useUiState } from "@/components/shell/ui-state";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { Project } from "@/lib/types";

export function ReviewQueuePopover({
  reviewCount,
  code,
}: {
  reviewCount?: number;
  code?: string | null;
}) {
  const { focusMode } = useUiState();
  const [open, setOpen] = useState(false);

  const { data } = useSWR<{ projects: Project[] }>(
    open ? "/api/proxy/projects" : null,
    proxyFetcher,
  );

  const flagged =
    data?.projects
      ?.filter((project) => project.counts.needsLook > 0)
      .sort((a, b) => {
        if (code && a.code === code) return -1;
        if (code && b.code === code) return 1;
        return b.counts.needsLook - a.counts.needsLook;
      }) ?? [];

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={
          reviewCount
            ? `Review queue — ${reviewCount} line${reviewCount === 1 ? "" : "s"} need a look`
            : "Review queue — nothing flagged"
        }
        title="Review queue"
        className="relative grid h-9 w-9 place-items-center rounded-lg border border-transparent bg-transparent p-0 text-tx-secondary hover:bg-panel-muted hover:border-subtle transition-all"
      >
        <Bell size={18} weight="duotone" />
        {!!reviewCount && !focusMode && (
          <span className="tnum absolute -right-1 -top-1 grid h-[18px] min-w-[18px] place-items-center rounded-full bg-status-error px-1 text-[10px] font-bold text-white shadow-sm ring-2 ring-background">
            {reviewCount}
          </span>
        )}
      </PopoverTrigger>
      <PopoverContent
        align="end"
        sideOffset={8}
        className="w-80 p-0 rounded-xl bg-panel border border-subtle shadow-xl shadow-black/10 text-tx-primary"
      >
        <PopoverHeader className="border-b border-subtle px-4 py-3 bg-panel-muted rounded-t-xl">
          <PopoverTitle className="text-[14px] font-bold tracking-tight">Review queue</PopoverTitle>
          <p className="text-[12px] font-medium text-tx-muted mt-0.5">
            Lines flagged for your review across open bids
          </p>
        </PopoverHeader>

        <div className={`overflow-auto py-1.5 ${flagged.length === 0 ? "" : "max-h-64"}`}>
          {flagged.length === 0 ? (
            <p className="px-4 py-3 text-[13px] font-medium text-tx-muted text-center">
              Nothing flagged for review
            </p>
          ) : (
            flagged.map((project) => (
              <Link
                key={project.id}
                href={`/bids/${project.code}/extraction`}
                onClick={() => setOpen(false)}
                className="flex items-center gap-3 px-4 py-3 no-underline transition-colors hover:bg-panel-muted group"
              >
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px] font-bold text-tx-primary group-hover:text-brand-primary transition-colors">
                    {project.jobName ?? project.name}
                  </span>
                  <span className="text-[12px] font-medium text-tx-muted mt-0.5 block">
                    {project.code}
                  </span>
                </span>
                <span className="tnum shrink-0 rounded-full px-2.5 py-1 text-[11px] font-bold bg-status-error-soft text-status-error">
                  {project.counts.needsLook}
                </span>
                <CaretRight size={14} className="text-tx-muted group-hover:text-tx-primary transition-colors" />
              </Link>
            ))
          )}
        </div>

        <div className="border-t border-subtle bg-panel-muted px-4 py-3 rounded-b-xl">
          <Link
            href="/bids?stage=extraction"
            onClick={() => setOpen(false)}
            className="text-[12px] font-bold no-underline text-brand-primary hover:text-brand-primary/80 transition-colors"
          >
            View all bids
          </Link>
        </div>
      </PopoverContent>
    </Popover>
  );
}
