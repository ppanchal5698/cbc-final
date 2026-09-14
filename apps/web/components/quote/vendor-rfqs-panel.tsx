"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { RFQ_TRIGGERS, nextRfqStatuses, type RfqTrigger } from "@/lib/rfq";
import type { VendorRfq } from "@/lib/types";

const inputClass =
  "rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";

const pillClass = "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest";

/**
 * FR-16, the third cost path: ask a vendor for a price the books cannot give.
 *
 * Tracks each request through the states the API enforces. Recording the price
 * that comes back and applying it to a line is still done on the quote grid.
 */
export function VendorRfqsPanel({ code }: { code: string }) {
  const url = `/api/proxy/projects/${encodeURIComponent(code)}/vendor-rfqs`;
  const { data, error, isLoading, mutate } = useSWR<{ vendorRfqs: VendorRfq[] }>(
    url,
    proxyFetcher,
  );
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const rfqs = data?.vendorRfqs ?? [];

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const quantity = Number(text("quantity"));
    const rfqNumber = text("rfqNumber");

    setBusy(true);
    try {
      await proxyMutate(url, {
        body: {
          rfqNumber,
          triggerReason: text("triggerReason"),
          requestedItems: [
            {
              description: text("description") || null,
              partNumber: text("partNumber") || null,
              quantity: Number.isFinite(quantity) && quantity > 0 ? quantity : null,
            },
          ],
          dueBy: text("dueBy") ? `${text("dueBy")}T00:00:00Z` : null,
          blocksBid: form.get("blocksBid") === "on",
        },
      });
      toast.success(`${rfqNumber} opened as a draft`);
      setAdding(false);
      mutate();
    } catch (problem) {
      toast.error("Could not open the vendor quote request", {
        description: errorMessage(problem),
      });
    } finally {
      setBusy(false);
    }
  }

  async function advance(rfq: VendorRfq, status: string) {
    try {
      await proxyMutate(`${url}/${rfq.id}`, { method: "PATCH", body: { status } });
      toast.success(`${rfq.rfqNumber} is now ${status}`);
      mutate();
    } catch (problem) {
      toast.error("Could not change the request's status", {
        description: errorMessage(problem),
      });
    }
  }

  return (
    <section
      aria-labelledby="vendor-rfqs-title"
      className="rounded-xl bg-panel border border-subtle shadow-sm"
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-subtle px-5 py-4">
        <div className="min-w-0 flex-1">
          <h2 id="vendor-rfqs-title" className="text-[15px] font-bold text-tx-primary tracking-tight">
            Vendor quote requests
          </h2>
          <p className="mt-1 text-[12.5px] font-medium text-tx-secondary">
            For custom sizes, non-stock and first-time items the price books cannot price.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          aria-expanded={adding}
          className="flex items-center gap-1.5 rounded-md px-3.5 py-2 text-[12.5px] font-semibold border border-subtle bg-panel shadow-sm hover:bg-panel-muted transition-colors text-tx-primary"
        >
          <Plus size={14} weight="bold" />
          New request
        </button>
      </div>

      {adding && (
        <form
          onSubmit={create}
          className="grid gap-3 border-b border-subtle bg-panel-muted px-5 py-4 sm:grid-cols-2"
        >
          <input
            name="rfqNumber"
            required
            placeholder="RFQ number, e.g. RFQ-1042"
            aria-label="RFQ number"
            className={inputClass}
          />
          <select
            name="triggerReason"
            required
            defaultValue="customSize"
            aria-label="Why a vendor quote is needed"
            className={inputClass}
          >
            {Object.entries(RFQ_TRIGGERS).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <input
            name="description"
            placeholder="Item, e.g. 4070 HM door, 90 min"
            aria-label="Item description"
            className={inputClass}
          />
          <input
            name="partNumber"
            placeholder="Part number (optional)"
            aria-label="Part number"
            className={inputClass}
          />
          <input
            name="quantity"
            type="number"
            min="1"
            step="1"
            placeholder="Quantity"
            aria-label="Quantity"
            className={inputClass}
          />
          <input name="dueBy" type="date" aria-label="Response due by" className={inputClass} />
          <label className="flex items-center gap-2 text-[12.5px] font-medium text-tx-secondary">
            <input name="blocksBid" type="checkbox" className="h-4 w-4" />
            Holds up the bid until the price is back
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
          >
            {busy ? "Opening…" : "Open as draft"}
          </button>
        </form>
      )}

      {error && (
        <div className="p-4">
          <FetchError
            title="Could not load vendor quote requests"
            error={error}
            onRetry={() => mutate()}
            compact
          />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="px-5 py-5 text-[13px] font-medium text-tx-muted">Loading…</p>
      )}
      {data && rfqs.length === 0 && (
        <p className="px-5 py-5 text-[13px] font-medium text-tx-muted">
          No vendor quotes requested on this bid.
        </p>
      )}

      <div className="divide-y divide-subtle">
        {rfqs.map((rfq) => (
          <div key={rfq.id} className="flex flex-wrap items-center gap-3 px-5 py-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13.5px] font-bold text-tx-primary">{rfq.rfqNumber}</span>
                <span className={`${pillClass} bg-panel-muted text-tx-secondary`}>{rfq.status}</span>
                {rfq.blocksBid && (
                  <span className={`${pillClass} bg-status-warning-soft text-status-warning`}>
                    blocks bid
                  </span>
                )}
              </div>
              <div className="mt-0.5 text-[12px] font-medium text-tx-muted">
                {RFQ_TRIGGERS[rfq.triggerReason as RfqTrigger] ?? rfq.triggerReason}
                {rfq.requestedItems?.[0]?.description ? ` · ${rfq.requestedItems[0].description}` : ""}
                {rfq.dueBy ? ` · due ${new Date(rfq.dueBy).toLocaleDateString()}` : ""}
              </div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {nextRfqStatuses(rfq.status).map((status) => (
                <button
                  key={status}
                  type="button"
                  onClick={() => advance(rfq, status)}
                  className="rounded-md px-2.5 py-1.5 text-[12px] font-semibold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
                >
                  {status === "cancelled" ? "Cancel" : `Mark ${status}`}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
