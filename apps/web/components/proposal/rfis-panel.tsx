"use client";

import { useState } from "react";
import useSWR from "swr";
import { Question } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { RFI_CATEGORIES, type RfiCategory } from "@/lib/rfq";
import type { Rfi } from "@/lib/types";

const inputClass =
  "w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";

/**
 * Phase 5: questions for the GC or architect before the quote is final.
 *
 * Also where a direct-equal substitution approval is sought (Matrix 6.4). The
 * API records RFIs; it has no route to move one on yet, so status is shown as-is.
 */
export function RfisPanel({ code }: { code: string }) {
  const url = `/api/proxy/projects/${encodeURIComponent(code)}/rfis`;
  const { data, error, isLoading, mutate } = useSWR<{ rfis: Rfi[] }>(url, proxyFetcher);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const rfis = data?.rfis ?? [];

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();

    setBusy(true);
    try {
      const created = await proxyMutate<Rfi>(url, {
        body: {
          subject: text("subject"),
          question: text("question"),
          category: text("category") || "other",
          blocksFinalization: form.get("blocksFinalization") === "on",
        },
      });
      toast.success(`${created?.rfiNumber ?? "RFI"} raised`);
      setAdding(false);
      mutate();
    } catch (problem) {
      toast.error("Could not raise the RFI", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="rfis-title"
      className="rounded-xl p-5 bg-panel border border-subtle shadow-sm"
    >
      <div className="flex items-center gap-2">
        <Question size={16} weight="duotone" className="text-tx-muted" />
        <h2 id="rfis-title" className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          RFIs
        </h2>
        <button
          type="button"
          onClick={() => setAdding((current) => !current)}
          aria-expanded={adding}
          className="ml-auto rounded-md px-2.5 py-1 text-[12px] font-semibold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
        >
          {adding ? "Close" : "Raise an RFI"}
        </button>
      </div>

      {adding && (
        <form onSubmit={create} className="mt-4 flex flex-col gap-2.5">
          <input name="subject" required placeholder="Subject" aria-label="RFI subject" className={inputClass} />
          <textarea
            name="question"
            required
            rows={3}
            placeholder="What is unclear, and what answer would unblock the quote?"
            aria-label="RFI question"
            className={inputClass}
          />
          <select name="category" defaultValue="other" aria-label="RFI category" className={inputClass}>
            {Object.entries(RFI_CATEGORIES).map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-[12.5px] font-medium text-tx-secondary">
            <input name="blocksFinalization" type="checkbox" className="h-4 w-4" />
            The quote cannot be finalized without the answer
          </label>
          <button
            type="submit"
            disabled={busy}
            className="rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
          >
            {busy ? "Raising…" : "Raise RFI"}
          </button>
        </form>
      )}

      {error && (
        <div className="mt-3">
          <FetchError title="Could not load RFIs" error={error} onRetry={() => mutate()} compact />
        </div>
      )}
      {isLoading && !data && !error && (
        <p className="mt-3 text-[12.5px] font-medium text-tx-muted">Loading…</p>
      )}
      {data && rfis.length === 0 && !adding && (
        <p className="mt-3 text-[12.5px] font-medium text-tx-muted">No RFIs raised on this bid.</p>
      )}

      {rfis.length > 0 && (
        <ul className="mt-4 flex flex-col gap-3">
          {rfis.map((rfi) => (
            <li key={rfi.id} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-bold text-tx-primary">{rfi.subject}</span>
                <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-panel-muted text-tx-secondary">
                  {rfi.status}
                </span>
                {rfi.blocksFinalization && (
                  <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning">
                    blocks final
                  </span>
                )}
              </span>
              <span className="text-[12px] font-medium text-tx-muted">
                {rfi.rfiNumber} · {RFI_CATEGORIES[rfi.category as RfiCategory] ?? rfi.category}
              </span>
              <span className="text-[12.5px] font-medium text-tx-secondary leading-relaxed">
                {rfi.question}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
