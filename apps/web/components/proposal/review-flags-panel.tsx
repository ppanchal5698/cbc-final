"use client";

import useSWR from "swr";
import { Flag } from "@phosphor-icons/react/dist/ssr";

import { FetchError } from "@/components/ui/fetch-error";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { ReviewFlag } from "@/lib/types";

const RANK: Record<string, number> = { critical: -1, high: 0, medium: 1, low: 2 };

const SEVERITY_STYLE: Record<string, string> = {
  critical: "bg-status-error-soft text-status-error",
  high: "bg-status-error-soft text-status-error",
  medium: "bg-status-warning-soft text-status-warning",
  low: "bg-panel-muted text-tx-secondary",
};

/**
 * NFR-2: every review flag on the bid, most severe first.
 *
 * The API derives them from the artifacts on each read and merges the
 * reviewer's own, so this is the current list, not the last pass's.
 */
export function ReviewFlagsPanel({ code }: { code: string }) {
  const { data, error, isLoading, mutate } = useSWR<{ flags: ReviewFlag[] }>(
    `/api/proxy/projects/${encodeURIComponent(code)}/review-flags`,
    proxyFetcher,
  );
  const flags = [...(data?.flags ?? [])].sort(
    (a, b) => (RANK[a.severity] ?? 3) - (RANK[b.severity] ?? 3),
  );
  const critical = flags.filter(
    (f) =>
      f.severity === "critical" ||
      f.field === "project_identity" ||
      f.category === "project_identity",
  );

  return (
    <section
      aria-labelledby="review-flags-title"
      className="rounded-xl p-5 bg-panel border border-subtle shadow-sm"
    >
      <div className="flex items-center gap-2">
        <Flag size={16} weight="duotone" className="text-status-warning" />
        <h2
          id="review-flags-title"
          className="text-[11px] font-bold uppercase tracking-widest text-tx-muted"
        >
          Review flags
        </h2>
        {data && (
          <span className="ml-auto text-[12px] font-bold text-tx-secondary">{flags.length}</span>
        )}
      </div>

      {critical.length > 0 && (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-status-error/40 bg-status-error-soft px-3 py-2 text-[12.5px] font-semibold text-status-error"
        >
          Critical: {critical.map((f) => f.note ?? f.issue ?? f.action_required).join(" · ")}
        </div>
      )}
      {error && (
        <div className="mt-3">
          <FetchError
            title="Could not load review flags"
            error={error}
            onRetry={() => mutate()}
            compact
          />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="mt-3 text-[12.5px] font-medium text-tx-muted">Reading flags…</p>
      )}
      {data && flags.length === 0 && (
        <p className="mt-3 text-[12.5px] font-medium text-tx-muted">Nothing flagged on this bid.</p>
      )}

      {flags.length > 0 && (
        <ul className="mt-4 flex max-h-[360px] flex-col gap-3 overflow-y-auto">
          {flags.map((flag, index) => (
            <li key={`${flag.opening}-${flag.field}-${index}`} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span
                  className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest ${
                    SEVERITY_STYLE[flag.severity] ?? SEVERITY_STYLE.low
                  }`}
                >
                  {flag.severity}
                </span>
                <span className="text-[13px] font-bold text-tx-primary">{flag.opening ?? flag.opening_id}</span>
                <span className="text-[12px] font-medium text-tx-muted">
                  {(flag.field ?? flag.category ?? "General review").replaceAll("_", " ")}
                </span>
              </span>
              <span className="text-[12.5px] font-medium text-tx-secondary leading-relaxed">
                {flag.note ?? flag.issue ?? flag.action_required}
                {flag.source_page ? ` · sheet page ${flag.source_page}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
