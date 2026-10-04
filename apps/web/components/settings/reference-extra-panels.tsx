"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Cube,
  Package,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type {
  SpecialNetsDoc,
  StockListDoc,
} from "@/lib/types";

const inputClass =
  "rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm w-full font-mono";


/** Hager special nets list. */
export function SpecialNetsPanel() {
  const { data, error, isLoading, mutate } = useSWR<SpecialNetsDoc>(
    "/api/proxy/reference/special-nets",
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ part_number: "", net_price: "" });

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/reference/special-nets", { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save special net", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full max-h-[480px]">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Package size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Hager special nets</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Fixed net overrides from the multiplier sheet.
        </p>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-3 overflow-auto flex-1">
          <form
            className="flex gap-2 mb-3"
            onSubmit={(e) => {
              e.preventDefault();
              const part = draft.part_number.trim();
              const net = Number(draft.net_price);
              if (!part || Number.isNaN(net)) {
                toast.error("Part number and net price required");
                return;
              }
              save({ items: [{ part_number: part, net_price: net }] }, `${part} saved`);
              setDraft({ part_number: "", net_price: "" });
            }}
          >
            <input
              className={inputClass}
              placeholder="Part"
              value={draft.part_number}
              onChange={(e) => setDraft((d) => ({ ...d, part_number: e.target.value }))}
              disabled={busy}
            />
            <input
              className={inputClass}
              placeholder="Net $"
              value={draft.net_price}
              onChange={(e) => setDraft((d) => ({ ...d, net_price: e.target.value }))}
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md px-3 py-2 text-[13px] font-semibold bg-brand-primary text-white shrink-0"
            >
              Add
            </button>
          </form>
          <ul className="text-[13px] space-y-1">
            {(data.items ?? []).slice(0, 40).map((item) => (
              <li key={item.part_number} className="flex justify-between gap-2 border-b border-subtle py-1">
                <span className="font-mono">{item.part_number}</span>
                <span>${Number(item.net_price).toFixed(2)}</span>
                <button
                  type="button"
                  className="text-status-error text-[12px]"
                  disabled={busy}
                  onClick={() => save({ remove: [item.part_number] }, `${item.part_number} removed`)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          {(data.items?.length ?? 0) > 40 && (
            <p className="text-[12px] text-tx-muted mt-2">Showing first 40 of {data.items?.length}</p>
          )}
        </div>
      )}
    </section>
  );
}


function StockVendorPanel({ vendor, title }: { vendor: string; title: string }) {
  const { data, error, isLoading, mutate } = useSWR<StockListDoc>(
    `/api/proxy/reference/stock/${vendor}`,
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [part, setPart] = useState("");

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/reference/stock/${vendor}`, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save stock list", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full max-h-[420px]">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Cube size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">{title}</h2>
        </div>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-3 overflow-auto flex-1">
          <form
            className="flex gap-2 mb-3"
            onSubmit={(e) => {
              e.preventDefault();
              const p = part.trim();
              if (!p) return;
              save({ items: [{ part_number: p }] }, `${p} added`);
              setPart("");
            }}
          >
            <input
              className={inputClass}
              placeholder="Part number"
              value={part}
              onChange={(e) => setPart(e.target.value)}
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md px-3 py-2 text-[13px] font-semibold bg-brand-primary text-white shrink-0"
            >
              Add
            </button>
          </form>
          <ul className="text-[13px] space-y-1">
            {(data.items ?? []).map((item) => (
              <li key={item.part_number} className="flex justify-between border-b border-subtle py-1">
                <span className="font-mono">{item.part_number}</span>
                <button
                  type="button"
                  className="text-status-error text-[12px]"
                  disabled={busy}
                  onClick={() => save({ remove: [item.part_number] }, `${item.part_number} removed`)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function StockListsPanel() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <StockVendorPanel vendor="hager" title="Hager top-10 stock" />
      <StockVendorPanel vendor="allegion" title="Allegion stock" />
    </div>
  );
}

