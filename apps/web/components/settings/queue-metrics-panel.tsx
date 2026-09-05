"use client";

import useSWR from "swr";

import { FetchError } from "@/components/ui/fetch-error";
import { endpoints } from "@/lib/endpoints";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { JobMetrics } from "@/lib/types";
import { cn } from "@/lib/utils";

/** How long ago, in words. The exact timestamp is not the point; "20m" is. */
function ago(iso: string | null): string {
  if (!iso) return "—";
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

function seconds(value: number | null): string {
  if (value === null) return "—";
  return value < 90 ? `${value.toFixed(0)}s` : `${(value / 60).toFixed(1)}m`;
}

/**
 * The queue, without reading `docker logs`.
 *
 * Until this existed the only operational view of the worker was its log stream,
 * which cannot answer "is it backed up" or "which job type is failing" without a
 * person scrolling. The numbers were always in MongoDB.
 */
export function QueueMetricsPanel() {
  const { data, error, isLoading, mutate } = useSWR<JobMetrics>(
    endpoints.jobMetrics(24),
    proxyFetcher,
    { refreshInterval: 15_000, keepPreviousData: true },
  );

  const types = Object.entries(data?.byType ?? {}).sort(
    (a, b) => b[1].total - a[1].total,
  );

  // Any failure at all is worth colouring. A queue that is merely busy is not.
  const failing = (data?.failed ?? 0) > 0;

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Job queue</h2>
        <p className="mt-1 text-[13px] font-medium text-tx-secondary">
          Depth now, and throughput over the last {data?.windowHours ?? 24} hours.
        </p>
      </div>

      <div className="px-5 py-4 flex-1">
        {error && (
          <FetchError title="Could not read the queue" error={error} onRetry={() => mutate()} />
        )}
        {isLoading && !data && (
          <p className="text-[13px] font-medium text-tx-muted">
            Reading the queue…
          </p>
        )}

        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              {[
                ["Queued", String(data.queued), undefined],
                ["Running", String(data.running), undefined],
                ["Oldest wait", ago(data.oldestQueuedAt), undefined],
                [
                  "Failure rate",
                  data.failureRate === null
                    ? "—"
                    : `${(data.failureRate * 100).toFixed(0)}%`,
                  failing ? "text-status-error" : undefined,
                ],
              ].map(([label, value, colorClass]) => (
                <div key={label as string} className="bg-background rounded-lg border border-subtle p-3 shadow-sm">
                  <p className="text-[12px] font-bold uppercase tracking-widest text-tx-muted mb-1">
                    {label}
                  </p>
                  <p className={cn("tnum text-[22px] font-bold tracking-tight", colorClass || "text-tx-primary")}>
                    {value}
                  </p>
                </div>
              ))}
            </div>

            {types.length > 0 && (
              <div className="mt-6 border border-subtle rounded-xl overflow-hidden shadow-sm">
                <table className="w-full text-[13px]">
                  <thead className="bg-panel-muted border-b border-subtle">
                    <tr>
                      <th className="px-4 py-2 text-left font-bold uppercase tracking-widest text-tx-muted text-[11px]">Job type</th>
                      <th className="px-4 py-2 text-right font-bold uppercase tracking-widest text-tx-muted text-[11px]">Done</th>
                      <th className="px-4 py-2 text-right font-bold uppercase tracking-widest text-tx-muted text-[11px]">Failed</th>
                      <th className="px-4 py-2 text-right font-bold uppercase tracking-widest text-tx-muted text-[11px]">Average</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-subtle bg-background">
                    {types.map(([type, row]) => (
                      <tr key={type} className="hover:bg-panel-muted transition-colors">
                        <td className="px-4 py-2.5 font-medium text-tx-primary">{type.replace(/_/g, " ")}</td>
                        <td className="tnum px-4 py-2.5 text-right font-medium text-tx-secondary">{row.done}</td>
                        <td
                          className={cn("tnum px-4 py-2.5 text-right font-medium", row.failed > 0 ? "text-status-error font-bold" : "text-tx-secondary")}
                        >
                          {row.failed}
                        </td>
                        <td className="tnum px-4 py-2.5 text-right font-medium text-tx-secondary">{seconds(row.avgSeconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {types.length === 0 && (
              <p className="mt-4 text-[13px] font-medium text-tx-muted bg-panel-muted border border-subtle rounded-lg px-4 py-3">
                No jobs in the window. Nothing is wrong; nothing has run.
              </p>
            )}
          </>
        )}
      </div>
    </section>
  );
}
