"use client";

import { useState } from "react";
import useSWR from "swr";
import { UserFocus, Plus, Trash, Warning } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/status-badge";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { SpecialMargins } from "@/lib/types";

const SPECIAL_URL = "/api/proxy/reference/special-margins";

function asPercent(margin: number): string {
  const pct = margin * 100;
  return `${pct.toFixed(pct % 1 === 0 ? 0 : 1)}%`;
}

/**
 * Edit special-customer margins (NR-9). A margin here is a sourcing-driven
 * override the pricing pass applies for that customer, with the note as its
 * recorded reason (margin-governance). Values are PENDING from CBC until entered.
 * Writes reference-library/multipliers/special_customer_margins.json.
 */
export function SpecialMarginsPanel() {
  const { data, error, isLoading, mutate } = useSWR<SpecialMargins>(SPECIAL_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newMargin, setNewMargin] = useState("");
  const [newNote, setNewNote] = useState("");

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<SpecialMargins>(SPECIAL_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that margin", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commitMargin(name: string, raw: string, current: number | null) {
    if (raw.trim() === "") {
      if (current === null) return;
      save({ customers: [{ name, margin: null }] }, `${name} margin cleared`);
      return;
    }
    const next = Number(raw);
    if (Number.isNaN(next) || next < 0 || next >= 1) {
      toast.error("Margin must be a fraction between 0 and 1", {
        description: `e.g. 0.30 for 30%. Got "${raw}".`,
      });
      mutate();
      return;
    }
    const rounded = Math.round(next * 10000) / 10000;
    if (rounded === current) return;
    save({ customers: [{ name, margin: rounded }] }, `${name} set to ${asPercent(rounded)}`);
  }

  function commitNote(name: string, raw: string, current: string) {
    if (raw.trim() === current.trim()) return;
    save({ customers: [{ name, note: raw.trim() }] }, `${name} reason updated`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) {
      toast.error("Give the customer a name");
      return;
    }
    let margin: number | null = null;
    if (newMargin.trim() !== "") {
      const parsed = Number(newMargin);
      if (Number.isNaN(parsed) || parsed < 0 || parsed >= 1) {
        toast.error("Margin must be a fraction between 0 and 1", { description: "e.g. 0.30 for 30%." });
        return;
      }
      margin = Math.round(parsed * 10000) / 10000;
    }
    save(
      { customers: [{ name, margin, note: newNote.trim() || null }] },
      `${name} added`,
    );
    setNewName("");
    setNewMargin("");
    setNewNote("");
  }

  function remove(name: string) {
    if (!window.confirm(`Remove ${name} from special-customer margins?`)) return;
    save({ remove: [name] }, `${name} removed`);
  }

  const customers = data?.customers ?? [];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <UserFocus size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Special-customer margins</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          A sourcing-driven margin override for a named account, with its reason recorded. Applied by
          the pricing pass; below-band lines are still flagged, not blocked. Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the special margins: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && (
        <div className="divide-y divide-subtle flex-1 overflow-y-auto">
          {customers.map((customer) => (
            <div key={customer.name} className="px-5 py-4 hover:bg-panel-muted transition-colors">
              <div className="flex items-center gap-4">
                <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-tx-primary">
                  {customer.name}
                </span>
                <StatusBadge variant={customer.margin === null ? "caution" : "neutral"}>
                  {customer.margin === null ? "Not set" : `= ${asPercent(customer.margin)}`}
                </StatusBadge>
                <input
                  key={`${customer.name}-${customer.margin}`}
                  type="number"
                  step="0.01"
                  min="0"
                  max="0.99"
                  defaultValue={customer.margin ?? ""}
                  disabled={busy}
                  placeholder="unset"
                  aria-label={`${customer.name} margin fraction`}
                  onBlur={(event) => commitMargin(customer.name, event.target.value, customer.margin)}
                  className="tnum w-24 shrink-0 rounded-md px-3 py-1.5 text-right text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
                />
                <button
                  type="button"
                  onClick={() => remove(customer.name)}
                  disabled={busy}
                  aria-label={`Remove ${customer.name}`}
                  className="shrink-0 rounded-md p-2 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors focus:ring-2 focus:ring-status-error"
                >
                  <Trash size={16} />
                </button>
              </div>
              <input
                key={`${customer.name}-note-${customer.note ?? ""}`}
                defaultValue={customer.note ?? ""}
                disabled={busy}
                placeholder="Reason for the override (recorded)"
                aria-label={`${customer.name} override reason`}
                onBlur={(event) => commitNote(customer.name, event.target.value, customer.note ?? "")}
                className="mt-3 w-full rounded-md px-3 py-2 text-[12.5px] font-medium outline-none border border-subtle bg-background text-tx-secondary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </div>
          ))}
        </div>
      )}

      {data && (
        <form
          onSubmit={add}
          className="flex flex-col gap-3 border-t border-subtle bg-panel-muted px-5 py-4 rounded-b-xl"
        >
          <div className="flex items-end gap-3">
            <label className="flex min-w-0 flex-1 flex-col gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Customer
              </span>
              <input
                value={newName}
                onChange={(event) => setNewName(event.target.value)}
                placeholder="e.g. Wendys"
                aria-label="New customer name"
                className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Margin
              </span>
              <input
                value={newMargin}
                onChange={(event) => setNewMargin(event.target.value)}
                type="number"
                step="0.01"
                min="0"
                max="0.99"
                placeholder="optional"
                aria-label="New customer margin"
                className="tnum w-24 rounded-md px-3 py-2 text-right text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="flex items-center justify-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50 h-[38px]"
            >
              <Plus size={16} weight="bold" />
              Add
            </button>
          </div>
          <input
            value={newNote}
            onChange={(event) => setNewNote(event.target.value)}
            placeholder="Reason for the override (recorded)"
            aria-label="New customer override reason"
            className="rounded-md px-3 py-2 text-[12.5px] font-medium outline-none border border-subtle bg-background text-tx-secondary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
          />
        </form>
      )}

      {data?.rule && (
        <p className="flex items-start gap-2.5 bg-status-warning-soft px-5 py-4 text-[12.5px] font-medium text-status-warning rounded-b-xl border-t border-status-warning/30">
          <Warning size={16} weight="duotone" className="mt-0.5 shrink-0" />
          {data.rule}
        </p>
      )}
    </section>
  );
}
