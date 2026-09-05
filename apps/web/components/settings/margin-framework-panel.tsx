"use client";

import { useState } from "react";
import useSWR from "swr";
import { Percent } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { MarginFramework } from "@/lib/types";

const MARGINS_URL = "/api/proxy/reference/margins";

function asPercent(margin: number): string {
  return `${(margin * 100).toFixed(margin * 100 % 1 === 0 ? 0 : 1)}%`;
}

/**
 * Edit the product-type margin bands (NFR-8). Writes reference-library/margins/
 * margin_framework.json through the API, which the pricing engine re-reads on
 * change - so an edit here is applied to the next line priced.
 */
export function MarginFrameworkPanel() {
  const { data, error, isLoading, mutate } = useSWR<MarginFramework>(MARGINS_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<MarginFramework>(MARGINS_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that margin", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  /** Validate, ignore no-ops, then persist a single band. */
  function commit(key: string, label: string, raw: string, current: number) {
    const next = Number(raw);
    if (raw.trim() === "" || Number.isNaN(next) || next < 0 || next >= 1) {
      toast.error("Margin must be a fraction between 0 and 1", {
        description: `e.g. 0.27 for 27%. Got "${raw}".`,
      });
      mutate();
      return;
    }
    const rounded = Math.round(next * 10000) / 10000;
    if (rounded === current) return;
    const payload = key === "accessories" ? { accessories: rounded } : { bands: { [key]: rounded } };
    save(payload, `${label} set to ${asPercent(rounded)}`);
  }

  const rows: { key: string; name: string; margin: number; examples?: string[] }[] = [
    ...(data?.bands ?? []).map((band) => ({
      key: band.key,
      name: band.name,
      margin: band.margin,
      examples: band.examples,
    })),
    ...(data && data.accessoriesDerived != null
      ? [
          {
            key: "accessories",
            name: "Restroom accessories",
            margin: data.accessoriesDerived,
            examples: ["derived to ~56% from the data"],
          },
        ]
      : []),
  ];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Percent size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Margin framework</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          The product-type margin applied as the editable default on every line. Sale = cost ÷ (1 −
          margin). Below-band lines are flagged, never blocked (NFR-8). Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the margin framework: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && (
        <div className="divide-y divide-subtle flex-1 overflow-y-auto">
          {rows.map((row) => {
            const divisor = Math.round((1 - row.margin) * 10000) / 10000;
            return (
              <div
                key={row.key}
                className="flex items-center gap-4 px-5 py-3 hover:bg-panel-muted transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <span className="block text-[13.5px] font-semibold text-tx-primary">{row.name}</span>
                  {row.examples && row.examples.length > 0 && (
                    <span className="block truncate text-[12px] font-medium text-tx-muted mt-0.5">
                      {row.examples.join(", ")}
                    </span>
                  )}
                </div>
                <span className="tnum shrink-0 text-[12.5px] font-medium text-tx-muted w-[104px] text-right">
                  {asPercent(row.margin)} · ÷ {divisor}
                </span>
                <input
                  key={`${row.key}-${row.margin}`}
                  type="number"
                  step="0.01"
                  min="0"
                  max="0.99"
                  defaultValue={row.margin}
                  disabled={busy}
                  aria-label={`${row.name} margin fraction`}
                  onBlur={(event) => commit(row.key, row.name, event.target.value, row.margin)}
                  className="tnum w-24 shrink-0 rounded-md px-3 py-1.5 text-right text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
                />
              </div>
            );
          })}
        </div>
      )}

      {data && (
        <p className="border-t border-subtle bg-panel-muted px-5 py-3 text-[11.5px] font-medium text-tx-muted rounded-b-xl">
          {data.source ? `${data.source}. ` : ""}
          Enter a fraction (0.27 = 27%). Saved on blur; the pricing engine picks up the change on the
          next line priced.
        </p>
      )}
    </section>
  );
}
