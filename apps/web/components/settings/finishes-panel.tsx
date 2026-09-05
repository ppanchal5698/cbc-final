"use client";

import { useState } from "react";
import useSWR from "swr";
import { Swatches, Plus, Trash, Warning } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { FinishCrosswalk } from "@/lib/types";

const FINISHES_URL = "/api/proxy/reference/finishes";

/**
 * Edit the dual finish crosswalk (NR-3) - US26D <-> 626, and so on. Read by the
 * matcher to reconcile nomenclature; US19 and US26D are DIFFERENT satins and must
 * stay distinct. Writes reference-library/finishes/finish_crosswalk.json.
 */
export function FinishesPanel() {
  const { data, error, isLoading, mutate } = useSWR<FinishCrosswalk>(FINISHES_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ us_code: "", numeric_code: "", description: "" });

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<FinishCrosswalk>(FINISHES_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that finish", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commitField(us_code: string, field: "numeric_code" | "description", raw: string, current: string) {
    const next = raw.trim();
    if (next === current.trim()) return;
    save({ finishes: [{ us_code, [field]: next || null }] }, `${us_code} updated`);
  }

  function togglePremium(us_code: string, current: boolean) {
    save({ finishes: [{ us_code, premium: !current }] }, `${us_code} marked ${!current ? "premium" : "standard"}`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const us_code = draft.us_code.trim();
    if (!us_code) {
      toast.error("Give the finish a US code, e.g. US26D");
      return;
    }
    save(
      {
        finishes: [
          {
            us_code,
            numeric_code: draft.numeric_code.trim() || null,
            description: draft.description.trim() || null,
            premium: false,
          },
        ],
      },
      `${us_code} added`,
    );
    setDraft({ us_code: "", numeric_code: "", description: "" });
  }

  function remove(us_code: string) {
    if (!window.confirm(`Remove the ${us_code} finish mapping?`)) return;
    save({ remove: [us_code] }, `${us_code} removed`);
  }

  const inputClass = "rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";
  const finishes = data?.finishes ?? [];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Swatches size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Finish crosswalk</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Dual nomenclature the matcher reconciles — US code ↔ numeric (BHMA). Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the crosswalk: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data?.warning && (
        <p className="mx-5 mt-4 flex items-start gap-2.5 bg-status-error-soft px-4 py-3 text-[12.5px] font-medium text-status-error rounded-lg border border-status-error/30 shadow-sm">
          <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
          {data.warning}
        </p>
      )}

      {data && (
        <div className="mt-4 divide-y divide-subtle flex-1 overflow-y-auto border-t border-subtle">
          {finishes.map((finish) => (
            <div
              key={finish.us_code}
              className="flex flex-wrap items-center gap-3 px-5 py-3.5 hover:bg-panel-muted transition-colors"
            >
              <span className="w-16 shrink-0 text-[14px] font-semibold text-tx-primary">{finish.us_code}</span>
              <input
                key={`${finish.us_code}-num-${finish.numeric_code ?? ""}`}
                defaultValue={finish.numeric_code ?? ""}
                disabled={busy}
                placeholder="numeric"
                aria-label={`${finish.us_code} numeric code`}
                onBlur={(event) => commitField(finish.us_code, "numeric_code", event.target.value, finish.numeric_code ?? "")}
                className={`tnum w-24 ${inputClass}`}
              />
              <input
                key={`${finish.us_code}-desc-${finish.description ?? ""}`}
                defaultValue={finish.description ?? ""}
                disabled={busy}
                placeholder="description"
                aria-label={`${finish.us_code} description`}
                onBlur={(event) => commitField(finish.us_code, "description", event.target.value, finish.description ?? "")}
                className={`min-w-0 flex-1 ${inputClass}`}
              />
              <button
                type="button"
                onClick={() => togglePremium(finish.us_code, finish.premium ?? false)}
                disabled={busy}
                aria-pressed={finish.premium ?? false}
                className={`shrink-0 rounded-md px-3 py-2 text-[11px] font-bold uppercase tracking-widest transition-colors shadow-sm ${
                  finish.premium
                    ? "bg-brand-primary/10 text-brand-primary border border-brand-primary/20"
                    : "bg-background text-tx-muted border border-subtle hover:text-tx-primary"
                }`}
              >
                Premium
              </button>
              <button
                type="button"
                onClick={() => remove(finish.us_code)}
                disabled={busy}
                aria-label={`Remove ${finish.us_code}`}
                className="shrink-0 rounded-md p-2 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors focus:ring-2 focus:ring-status-error"
              >
                <Trash size={16} />
              </button>
            </div>
          ))}
        </div>
      )}

      {data && (
        <form
          onSubmit={add}
          className="flex flex-wrap items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4 rounded-b-xl"
        >
          <input
            value={draft.us_code}
            onChange={(event) => setDraft((d) => ({ ...d, us_code: event.target.value }))}
            placeholder="US code"
            aria-label="New finish US code"
            className={`w-28 ${inputClass}`}
          />
          <input
            value={draft.numeric_code}
            onChange={(event) => setDraft((d) => ({ ...d, numeric_code: event.target.value }))}
            placeholder="Numeric"
            aria-label="New finish numeric code"
            className={`w-24 ${inputClass}`}
          />
          <input
            value={draft.description}
            onChange={(event) => setDraft((d) => ({ ...d, description: event.target.value }))}
            placeholder="Description"
            aria-label="New finish description"
            className={`min-w-0 flex-1 ${inputClass}`}
          />
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
