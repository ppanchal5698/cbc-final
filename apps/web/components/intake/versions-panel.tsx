"use client";

import { useState } from "react";
import useSWR from "swr";
import { Checks, ClockCounterClockwise, Warning } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { FetchError } from "@/components/ui/fetch-error";
import type { VersionDiff, VersionsResponse } from "@/lib/types";

/**
 * Addendum snapshots and diffs — interim UI for FR-14 until Matrix 4.1 rules land.
 */
export function VersionsPanel({ code }: { code: string }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [busy, setBusy] = useState(false);

  const { data, error, mutate } = useSWR<VersionsResponse>(
    `/api/proxy/projects/${code}/versions`,
    proxyFetcher,
  );

  const versions = data?.versions ?? [];

  if (error) {
    return (
      <section className="rounded-xl bg-panel border border-subtle shadow-sm">
        <FetchError
          title="Could not load addendum versions"
          error={error}
          onRetry={() => mutate()}
        />
      </section>
    );
  }

  if (versions.length === 0) return null;

  async function loadDiff(version: number) {
    if (expanded === version) {
      setExpanded(null);
      setDiff(null);
      return;
    }
    setExpanded(version);
    setDiff(null);
    try {
      setDiff(
        await proxyFetcher<VersionDiff>(`/api/proxy/projects/${code}/versions/${version}/diff`),
      );
    } catch (problem) {
      toast.error("Could not load the diff", { description: errorMessage(problem) });
    }
  }

  async function reconcile(version: number) {
    if (
      !window.confirm(
        "Mark this addendum as reviewed? This does not merge changes automatically — compare the diff manually before pricing.",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}/versions/${version}/reconcile`);
      toast.success(`Version ${version} marked reviewed`);
      mutate();
    } catch (problem) {
      toast.error("Could not mark reviewed", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  const unreconciled = (data?.unreconciled ?? 0) > 0;

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="flex items-center gap-3 border-b border-subtle px-5 py-4">
        <ClockCounterClockwise size={18} weight="fill" className="text-brand-primary" />
        <span className="text-[16px] font-bold tracking-tight">Addendum versions</span>
        {data?.unreconciled ? (
          <span className="rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning shadow-sm">
            {data.unreconciled} unreconciled
          </span>
        ) : null}
      </div>

      <div className="divide-y divide-subtle">
        {versions.map((entry) => (
          <div key={entry.id} className="px-5 py-4 hover:bg-background/50 transition-colors">
            <div className="flex flex-wrap items-start gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-3">
                  <span className="text-[14px] font-bold">v{entry.version}</span>
                  <span className="text-[13px] font-medium text-tx-secondary">
                    {entry.reason}
                  </span>
                  {entry.reconciled ? (
                    <span className="text-[11px] font-bold uppercase tracking-widest text-status-success bg-status-success-soft px-2 py-0.5 rounded-full shadow-sm">
                      reconciled
                    </span>
                  ) : null}
                </div>
                <p className="mt-1.5 text-[12px] font-medium text-tx-muted">
                  {entry.lineItemCount} line items · {entry.quoteLineCount} quote lines · by{" "}
                  {entry.createdBy}
                </p>
              </div>
              <button
                onClick={() => loadDiff(entry.version)}
                className="rounded-lg px-3 py-1.5 text-[12px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
              >
                {expanded === entry.version ? "Hide diff" : "View diff"}
              </button>
              {!entry.reconciled && (
                <button
                  onClick={() => reconcile(entry.version)}
                  disabled={busy}
                  className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-bold disabled:opacity-50 bg-brand-primary text-white hover:bg-brand-primary/90 transition-colors shadow-sm"
                >
                  <Checks size={14} weight="bold" />
                  Mark reviewed
                </button>
              )}
            </div>

            {expanded === entry.version && diff && (
              <div className="mt-4 rounded-xl p-4 text-[13px] font-medium bg-panel-muted border border-subtle shadow-inner">
                {diff.added.length > 0 && (
                  <p>
                    <strong className="text-tx-primary font-bold">Added:</strong> {diff.added.join(", ") || "—"}
                  </p>
                )}
                {diff.removed.length > 0 && (
                  <p className="mt-1.5">
                    <strong className="text-tx-primary font-bold">Removed:</strong> {diff.removed.join(", ") || "—"}
                  </p>
                )}
                {diff.changed.length > 0 && (
                  <ul className="mt-3 flex flex-col gap-1.5">
                    {diff.changed.map((row) => (
                      <li key={row.mark} className="text-tx-secondary">
                        <strong className="text-tx-primary font-bold">{row.mark}</strong> — {row.fields.join(", ")} changed
                      </li>
                    ))}
                  </ul>
                )}
                {diff.added.length === 0 && diff.removed.length === 0 && diff.changed.length === 0 && (
                  <p className="text-tx-muted italic">No line-item changes detected against this snapshot.</p>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      <p
        className={`flex items-center gap-2 border-t border-subtle px-5 py-3 text-[12px] font-medium transition-colors ${
          unreconciled ? "text-status-warning bg-status-warning-soft/30" : "text-tx-muted"
        }`}
        title={data?.pending}
      >
        {unreconciled ? <Warning size={14} weight="fill" /> : null}
        Mark reviewed records that you compared this addendum against the prior version.
        Automatic merge rules are not yet available — review changes manually before pricing.
      </p>
    </section>
  );
}
