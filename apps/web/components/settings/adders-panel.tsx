"use client";

import { useState } from "react";
import useSWR from "swr";
import { Stack, Plus, Trash } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { formatMoney } from "@/lib/format";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { ManualAdders } from "@/lib/types";

const ADDERS_URL = "/api/proxy/reference/adders";

/**
 * Edit the Hager list adders (NR-4). These are LIST dollar amounts the pricing
 * pass multiplies by the base item's category multiplier - they are never in a
 * price-book lookup. Writes reference-library/adders/manual_adders.json, which the
 * next pricing run reads.
 */
export function AddersPanel() {
  const { data, error, isLoading, mutate } = useSWR<ManualAdders>(ADDERS_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newAmount, setNewAmount] = useState("");

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<ManualAdders>(ADDERS_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that adder", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commit(name: string, raw: string, current: number) {
    const next = Number(raw);
    if (raw.trim() === "" || Number.isNaN(next) || next < 0) {
      toast.error("Adder must be a dollar amount of 0 or more", { description: `Got "${raw}".` });
      mutate();
      return;
    }
    const rounded = Math.round(next * 100) / 100;
    if (rounded === current) return;
    save({ items: { [name]: rounded } }, `${name} set to $${formatMoney(rounded)}`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    const amount = Number(newAmount);
    if (!name) {
      toast.error("Give the adder a name");
      return;
    }
    if (newAmount.trim() === "" || Number.isNaN(amount) || amount < 0) {
      toast.error("Adder must be a dollar amount of 0 or more");
      return;
    }
    save({ items: { [name]: Math.round(amount * 100) / 100 } }, `${name} added`);
    setNewName("");
    setNewAmount("");
  }

  function remove(name: string) {
    if (!window.confirm(`Remove the "${name}" adder?`)) return;
    save({ remove: [name] }, `${name} removed`);
  }

  const items = data?.hagerListAdders.items ?? [];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Stack size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Manual adders</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Hager list adders, in dollars — added on top of the base price, then multiplied by the
          item&apos;s category multiplier. Never part of a price-book lookup. Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the adders: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && (
        <div className="divide-y divide-subtle flex-1 overflow-y-auto">
          {items.map((item) => (
            <div
              key={item.name}
              className="flex items-center gap-4 px-5 py-3 hover:bg-panel-muted transition-colors"
            >
              <span className="min-w-0 flex-1 truncate text-[14px] font-semibold text-tx-primary">{item.name}</span>
              <span className="tnum shrink-0 text-[12.5px] font-medium text-tx-muted">
                $
              </span>
              <input
                key={`${item.name}-${item.list_adder}`}
                type="number"
                step="0.01"
                min="0"
                defaultValue={item.list_adder}
                disabled={busy}
                aria-label={`${item.name} list adder`}
                onBlur={(event) => commit(item.name, event.target.value, item.list_adder)}
                className="tnum w-24 shrink-0 rounded-md px-3 py-1.5 text-right text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
              <button
                type="button"
                onClick={() => remove(item.name)}
                disabled={busy}
                aria-label={`Remove ${item.name}`}
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
          className="flex items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4"
        >
          <label className="flex min-w-0 flex-1 flex-col gap-1.5">
            <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              Adder
            </span>
            <input
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              placeholder="e.g. Lead lined"
              aria-label="New adder name"
              className="rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              List $
            </span>
            <input
              value={newAmount}
              onChange={(event) => setNewAmount(event.target.value)}
              type="number"
              step="0.01"
              min="0"
              placeholder="0.00"
              aria-label="New adder list amount"
              className="tnum w-24 rounded-md px-3 py-2 text-right text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
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

      {data && data.adderTypes.length > 0 && (
        <div className="border-t border-subtle bg-panel-muted px-5 py-4 rounded-b-xl">
          <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
            Adder categories (no single value — priced per series)
          </span>
          <ul className="mt-2.5 flex flex-col gap-2">
            {data.adderTypes.map((type) => (
              <li key={type.type} className="text-[12.5px] font-medium text-tx-secondary">
                <span className="font-semibold capitalize text-tx-primary">{type.type}</span>
                {type.note.includes("PENDING") && (
                  <span className="ml-2 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning">
                    Pending CBC
                  </span>
                )}
                <span className="text-tx-muted"> — {type.note}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
