"use client";

import { useState } from "react";
import useSWR from "swr";
import { ArrowsLeftRight } from "@phosphor-icons/react";

import { proxyFetcher } from "@/lib/proxy-fetcher";
import { formatMoneyShort } from "@/lib/format";
import { cn } from "@/lib/utils";

interface Prior {
  id: string;
  code: string;
  name: string;
  brand?: string | null;
  architect?: string | null;
  gc?: string | null;
  quoteTotal?: number | null;
  lineCount?: number | null;
}

/**
 * This bid against the closest prior one.
 *
 * FR-11 already finds the neighbours - same brand, architect or GC - for
 * seeding a templated bid. The same list answers a different question at the
 * end: is this number in the right place next to the last one we sent them.
 */
export function PriorBidCompare({
  code,
  total,
  lineCount,
}: {
  code: string;
  total: number;
  lineCount: number;
}) {
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useSWR<{ priors: Prior[] }>(
    open ? `/api/proxy/projects/${encodeURIComponent(code)}/prior-quotes` : null,
    proxyFetcher,
  );

  const prior = data?.priors?.[0];
  const priorTotal = prior?.quoteTotal ?? null;
  const delta = priorTotal ? Math.round(((total - priorTotal) / priorTotal) * 100) : null;

  return (
    <div className="rounded-xl border border-subtle bg-panel p-5 shadow-1">
      <button
        type="button"
        onClick={() => setOpen((current) => !current)}
        className="flex w-full items-center gap-2 text-left"
      >
        <ArrowsLeftRight size={16} weight="duotone" className="text-brand-primary" />
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          Compare with a previous bid
        </span>
        <span className="flex-1" />
        <span className="text-[12px] font-semibold text-brand-primary">
          {open ? "Hide" : "Show"}
        </span>
      </button>

      {open && (
        <div className="mt-4">
          {isLoading && (
            <p className="text-[12.5px] font-medium text-tx-muted">Looking for a close one…</p>
          )}
          {data && !prior && (
            <p className="text-[12.5px] font-medium leading-relaxed text-tx-muted">
              No prior bid for this brand, architect or GC to compare against.
            </p>
          )}
          {prior && (
            <>
              <div className="leading-tight">
                <span className="block text-[13px] font-semibold text-tx-primary">
                  {prior.name}
                </span>
                <span className="block text-[11.5px] font-medium text-tx-muted">
                  {prior.code}
                  {prior.brand ? ` · ${prior.brand}` : ""}
                </span>
              </div>

              <div
                className="mt-3 grid items-center gap-2 border-b border-subtle pb-1.5 text-[10px] font-bold uppercase tracking-widest text-tx-muted"
                style={{ gridTemplateColumns: "minmax(0,1fr) 62px 62px 58px" }}
              >
                <span />
                <span className="text-right">Then</span>
                <span className="text-right">Now</span>
                <span className="text-right">Diff</span>
              </div>

              {[
                {
                  label: "Quoted value",
                  then: priorTotal === null ? "—" : formatMoneyShort(priorTotal),
                  now: formatMoneyShort(total),
                  diff: delta === null ? "—" : `${delta > 0 ? "+" : ""}${delta}%`,
                  warn: delta !== null && delta > 0,
                },
                {
                  label: "Lines",
                  then: prior.lineCount == null ? "—" : String(prior.lineCount),
                  now: String(lineCount),
                  diff:
                    prior.lineCount == null
                      ? "—"
                      : `${lineCount - prior.lineCount > 0 ? "+" : ""}${lineCount - prior.lineCount}`,
                  warn: false,
                },
              ].map((row) => (
                <div
                  key={row.label}
                  className="grid items-center gap-2 border-b border-subtle py-2 text-[12.5px] last:border-b-0"
                  style={{ gridTemplateColumns: "minmax(0,1fr) 62px 62px 58px" }}
                >
                  <span className="truncate font-medium text-tx-secondary">{row.label}</span>
                  <span className="tnum text-right font-medium text-tx-muted">{row.then}</span>
                  <span className="tnum text-right font-semibold text-tx-primary">{row.now}</span>
                  <span
                    className={cn(
                      "tnum text-right font-bold",
                      row.warn ? "text-status-warning" : "text-tx-secondary",
                    )}
                  >
                    {row.diff}
                  </span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
