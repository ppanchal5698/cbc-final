"use client";

import useSWR from "swr";
import { UserCircleCheck } from "@phosphor-icons/react/dist/ssr";

import { errorMessage, proxyFetcher } from "@/lib/proxy-fetcher";
import type { StewardshipResponse } from "@/lib/types";

const LABELS: Record<string, string> = {
  vendor_tiers: "Vendor multipliers and tiers",
  hardware_equals: "Allegion equals",
  hager_special_nets: "Hager special nets",
  margins: "Margin sheet",
  hager_top10_stock: "Hager stock list",
  allegion_stock: "Allegion stock list",
  special_customer_margins: "Special-customer margins",
  tax: "Tax rates",
};

function day(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "—";
}

/**
 * NFR-10 (requirements 6.3): who keeps each data set current, when it last
 * changed, and when it is next due for review. A set past its review is due,
 * not refused - pricing still reads it.
 */
export function StewardshipPanel() {
  const { data, error } = useSWR<StewardshipResponse>("/api/proxy/reference/stewardship", proxyFetcher);

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <UserCircleCheck size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Data stewardship</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">{data?.note}</p>
      </div>
      {error ? (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the stewardship: {errorMessage(error)}
        </p>
      ) : (
        <div className="overflow-x-auto px-5 py-3">
          <table className="w-full min-w-[640px] text-[12.5px]">
            <thead>
              <tr className="text-left text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                <th className="py-1.5 pr-3">Data set</th>
                <th className="py-1.5 pr-3">Owner</th>
                <th className="py-1.5 pr-3">Refresh</th>
                <th className="py-1.5 pr-3">Last changed</th>
                <th className="py-1.5 pr-3">Next review</th>
              </tr>
            </thead>
            <tbody>
              {(data?.sets ?? []).map((set) => (
                <tr key={set.family} className="border-t border-subtle">
                  <td className="py-2 pr-3 font-semibold text-tx-primary">{LABELS[set.family] ?? set.family}</td>
                  <td className="py-2 pr-3 text-tx-secondary">{set.owner}</td>
                  <td className="py-2 pr-3 text-tx-secondary">{set.cadence}</td>
                  <td className="py-2 pr-3 text-tx-secondary" title={set.updatedBy ?? undefined}>
                    {set.updatedAt ? day(set.updatedAt) : "not since setup"}
                  </td>
                  <td className="py-2 pr-3">
                    {set.due ? (
                      <span className="rounded-md border border-status-warning/30 bg-status-warning-soft px-1.5 py-0.5 text-[10.5px] font-bold uppercase tracking-widest text-status-warning">
                        due
                      </span>
                    ) : (
                      <span className="text-tx-secondary">{set.reviewDue ? day(set.reviewDue) : "on change"}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
