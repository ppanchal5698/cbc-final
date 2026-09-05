"use client";

import useSWR from "swr";

import { FetchError } from "@/components/ui/fetch-error";
import { endpoints } from "@/lib/endpoints";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { SpendSummary } from "@/lib/types";
import { jobTypeLabel } from "@/lib/job-error";
import { cn } from "@/lib/utils";

function usd(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `$${value.toFixed(2)}`;
}

function pct(ratio: number | null | undefined): string {
  if (ratio === null || ratio === undefined) return "—";
  return `${(ratio * 100).toFixed(0)}%`;
}

export function SpendOpsPanel() {
  const { data, error, isLoading, mutate } = useSWR<SpendSummary>(
    endpoints.opsSpend(24),
    proxyFetcher,
    { refreshInterval: 30_000, keepPreviousData: true },
  );

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <FetchError title="Could not read spend" error={error} onRetry={() => mutate()} />
      )}
      {isLoading && !data && (
        <p className="text-[13px] font-medium text-tx-muted">Reading run metrics…</p>
      )}

      {data && (
        <>
          <section className="rounded-xl border border-subtle bg-panel shadow-sm">
            <div className="border-b border-subtle px-5 py-4">
              <h2 className="text-[16px] font-bold tracking-tight text-tx-primary">
                Last {data.windowHours} hours
              </h2>
              <p className="mt-1 text-[13px] font-medium text-tx-secondary">
                Claim caps (`WORKER_MAX_COST_*`) gate the queue; this page shows what
                `runMetrics` recorded.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-4 p-5 sm:grid-cols-4">
              {[
                ["Spend", usd(data.totalCostUsd), data.overDailyCap ? "text-status-error" : undefined],
                ["Runs", String(data.runs), undefined],
                [
                  "Daily cap",
                  data.dailyCapUsd === null ? "unlimited" : usd(data.dailyCapUsd),
                  undefined,
                ],
                [
                  "Project cap",
                  data.projectCapUsd === null ? "unlimited" : usd(data.projectCapUsd),
                  undefined,
                ],
              ].map(([label, value, colorClass]) => (
                <div
                  key={label as string}
                  className="rounded-lg border border-subtle bg-background p-3 shadow-sm"
                >
                  <div className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    {label}
                  </div>
                  <div
                    className={cn(
                      "mt-1 text-[20px] font-bold tabular-nums text-tx-primary",
                      colorClass as string | undefined,
                    )}
                  >
                    {value}
                  </div>
                </div>
              ))}
            </div>
            {data.overDailyCap && (
              <p className="border-t border-status-error/20 bg-status-error-soft px-5 py-3 text-[13px] font-medium text-status-error">
                Daily spend is at or over the configured worker cap. New claims stay
                queued until the window rolls or the cap is raised.
              </p>
            )}
          </section>

          <section className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm">
            <div className="border-b border-subtle px-5 py-4">
              <h2 className="text-[15px] font-bold text-tx-primary">By job type</h2>
            </div>
            <table className="w-full border-collapse text-left text-[13px]">
              <thead className="border-b border-subtle bg-panel-muted text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                <tr>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Runs</th>
                  <th className="px-4 py-3">Spend</th>
                </tr>
              </thead>
              <tbody>
                {data.byType.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-tx-muted">
                      No billed runs in this window.
                    </td>
                  </tr>
                ) : (
                  data.byType.map((row) => (
                    <tr key={row.jobType} className="border-b border-subtle last:border-0">
                      <td className="px-4 py-3 text-tx-secondary">
                        {jobTypeLabel(row.jobType)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-tx-primary">{row.runs}</td>
                      <td className="px-4 py-3 tabular-nums font-semibold text-tx-primary">
                        {usd(row.totalCostUsd)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>

          <section className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm">
            <div className="border-b border-subtle px-5 py-4">
              <h2 className="text-[15px] font-bold text-tx-primary">Top projects</h2>
            </div>
            <table className="w-full border-collapse text-left text-[13px]">
              <thead className="border-b border-subtle bg-panel-muted text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                <tr>
                  <th className="px-4 py-3">Project</th>
                  <th className="px-4 py-3">Runs</th>
                  <th className="px-4 py-3">Spend</th>
                </tr>
              </thead>
              <tbody>
                {data.byProject.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="px-4 py-6 text-tx-muted">
                      No project spend yet.
                    </td>
                  </tr>
                ) : (
                  data.byProject.map((row) => (
                    <tr
                      key={`${row.projectId}-${row.projectSlug}`}
                      className="border-b border-subtle last:border-0"
                    >
                      <td className="px-4 py-3 font-medium text-tx-primary">
                        {row.projectSlug || row.projectId || "—"}
                        {row.overProjectCap ? (
                          <span className="ml-2 text-[11px] font-bold uppercase text-status-error">
                            over cap
                          </span>
                        ) : null}
                      </td>
                      <td className="px-4 py-3 tabular-nums">{row.runs}</td>
                      <td className="px-4 py-3 tabular-nums font-semibold">
                        {usd(row.totalCostUsd)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>

          <section className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm">
            <div className="border-b border-subtle px-5 py-4">
              <h2 className="text-[15px] font-bold text-tx-primary">Recent runs</h2>
            </div>
            <table className="w-full border-collapse text-left text-[13px]">
              <thead className="border-b border-subtle bg-panel-muted text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                <tr>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Type</th>
                  <th className="px-4 py-3">Project</th>
                  <th className="px-4 py-3">Cost</th>
                  <th className="px-4 py-3">Cache hit</th>
                </tr>
              </thead>
              <tbody>
                {data.recent.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-tx-muted">
                      No recent runMetrics documents.
                    </td>
                  </tr>
                ) : (
                  data.recent.map((row) => (
                    <tr key={String(row.id)} className="border-b border-subtle last:border-0">
                      <td className="whitespace-nowrap px-4 py-3 text-tx-muted">
                        {row.startedAt
                          ? new Date(row.startedAt).toLocaleString()
                          : "—"}
                      </td>
                      <td className="px-4 py-3 text-tx-secondary">
                        {row.jobType ? jobTypeLabel(row.jobType) : "—"}
                      </td>
                      <td className="px-4 py-3 text-tx-primary">
                        {row.projectSlug || row.projectId || "—"}
                      </td>
                      <td className="px-4 py-3 tabular-nums font-semibold">
                        {usd(row.totalCostUsd)}
                      </td>
                      <td className="px-4 py-3 tabular-nums text-tx-muted">
                        {pct(row.cacheHitRatio)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}
