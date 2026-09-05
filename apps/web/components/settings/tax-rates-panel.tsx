"use client";

import { useState } from "react";
import useSWR from "swr";
import { MapPinLine, Plus, Trash } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { TaxRates } from "@/lib/types";

const TAX_URL = "/api/proxy/reference/tax";

function asPercent(rate: number): string {
  const pct = rate * 100;
  return `${pct.toFixed(pct % 1 === 0 ? 0 : 2)}%`;
}

/**
 * Edit nexus sales-tax rates. Writes reference-library/tax/sales_tax_rates.json
 * through the API, which the pricing engine re-reads on change. States absent
 * from the table are untaxed by design - this lists only where CBC has nexus.
 */
export function TaxRatesPanel() {
  const { data, error, isLoading, mutate } = useSWR<TaxRates>(TAX_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [newCode, setNewCode] = useState("");
  const [newRate, setNewRate] = useState("");

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<TaxRates>(TAX_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that tax rate", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commit(code: string, raw: string, current: number) {
    const next = Number(raw);
    if (raw.trim() === "" || Number.isNaN(next) || next < 0 || next >= 1) {
      toast.error("Tax rate must be a fraction between 0 and 1", {
        description: `e.g. 0.08 for 8%. Got "${raw}".`,
      });
      mutate();
      return;
    }
    const rounded = Math.round(next * 100000) / 100000;
    if (rounded === current) return;
    save({ rates: { [code]: rounded } }, `${code} set to ${asPercent(rounded)}`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const code = newCode.trim().toUpperCase();
    const rate = Number(newRate);
    if (!/^[A-Z]{2}$/.test(code)) {
      toast.error("Enter a two-letter state code", { description: `Got "${newCode}".` });
      return;
    }
    if (newRate.trim() === "" || Number.isNaN(rate) || rate < 0 || rate >= 1) {
      toast.error("Rate must be a fraction between 0 and 1", { description: "e.g. 0.08 for 8%." });
      return;
    }
    save({ rates: { [code]: rate } }, `${code} added at ${asPercent(rate)}`);
    setNewCode("");
    setNewRate("");
  }

  function remove(code: string) {
    if (!window.confirm(`Remove ${code}? CBC would no longer charge tax there (0% rate).`)) return;
    save({ remove: [code] }, `${code} removed`);
  }

  const entries = Object.entries(data?.rates ?? {}).sort(([a], [b]) => a.localeCompare(b));

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <MapPinLine size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Sales tax by jurisdiction</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Rates for the states where CBC has nexus. Every other state and Canada is untaxed. Applied
          from the ship-to location; an unknown project state stays pending, never zero.
          Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the tax table: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && (
        <div className="divide-y divide-subtle flex-1 overflow-y-auto">
          {entries.map(([code, rate]) => (
            <div
              key={code}
              className="flex items-center gap-4 px-5 py-3 hover:bg-panel-muted transition-colors"
            >
              <span className="w-12 shrink-0 text-[13.5px] font-semibold text-tx-primary">{code}</span>
              <span className="flex-1 text-[12.5px] font-medium text-tx-secondary">
                = {asPercent(rate)}
              </span>
              <input
                key={`${code}-${rate}`}
                type="number"
                step="0.001"
                min="0"
                max="0.99"
                defaultValue={rate}
                disabled={busy}
                aria-label={`${code} tax rate fraction`}
                onBlur={(event) => commit(code, event.target.value, rate)}
                className="tnum w-24 shrink-0 rounded-md px-3 py-1.5 text-right text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
              <button
                type="button"
                onClick={() => remove(code)}
                disabled={busy}
                aria-label={`Remove ${code}`}
                className="shrink-0 rounded-md p-2 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors focus:ring-2 focus:ring-status-error"
              >
                <Trash size={16} />
              </button>
            </div>
          ))}
          {entries.length === 0 && (
            <p className="px-5 py-4 text-[13px] font-medium text-tx-muted">
              No nexus jurisdictions on file — every quote is untaxed.
            </p>
          )}
        </div>
      )}

      {data && (
        <form
          onSubmit={add}
          className="flex items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4 rounded-b-xl"
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              State
            </span>
            <input
              value={newCode}
              onChange={(event) => setNewCode(event.target.value.toUpperCase().slice(0, 2))}
              placeholder="IN"
              aria-label="New jurisdiction state code"
              className="w-16 rounded-md px-3 py-2 text-[13px] uppercase outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              Rate (fraction)
            </span>
            <input
              value={newRate}
              onChange={(event) => setNewRate(event.target.value)}
              type="number"
              step="0.001"
              min="0"
              max="0.99"
              placeholder="0.07"
              aria-label="New jurisdiction tax rate"
              className="tnum w-24 rounded-md px-3 py-2 text-right text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
            />
          </label>
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50 h-[38px]"
          >
            <Plus size={16} weight="bold" />
            Add
          </button>
        </form>
      )}
    </section>
  );
}
