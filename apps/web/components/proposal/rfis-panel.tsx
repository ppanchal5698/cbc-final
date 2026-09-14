"use client";

import { useState } from "react";
import useSWR from "swr";
import { Question } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { RFI_CATEGORIES, nextRfiStatuses, type RfiCategory } from "@/lib/rfq";
import type { Rfi } from "@/lib/types";

const inputClass =
  "w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";

const pillClass = "rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest";

const ACTION_LABEL: Record<string, string> = {
  sent: "Mark sent",
  answered: "Record answer",
  closed: "Close",
  withdrawn: "Withdraw",
};

/**
 * Phase 5: questions for the GC or architect before the quote is final.
 *
 * Also where a direct-equal substitution approval is sought (Matrix 6.4). An RFI
 * moves through the states the API enforces, and answering one records the answer.
 */
export function RfisPanel({ code }: { code: string }) {
  const url = `/api/proxy/projects/${encodeURIComponent(code)}/rfis`;
  const { data, error, isLoading, mutate } = useSWR<{ rfis: Rfi[] }>(url, proxyFetcher);
  const [adding, setAdding] = useState(false);
  const [answering, setAnswering] = useState<string | null>(null);
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

  async function move(rfi: Rfi, status: string, answer?: string) {
    setBusy(true);
    try {
      await proxyMutate(`${url}/${rfi.id}`, {
        method: "PATCH",
        body: answer === undefined ? { status } : { status, answer },
      });
      toast.success(`${rfi.rfiNumber} is now ${status}`);
      setAnswering(null);
      mutate();
    } catch (problem) {
      toast.error("Could not change the RFI", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  function advance(rfi: Rfi, status: string) {
    if (status === "answered") {
      setAnswering((current) => (current === rfi.id ? null : rfi.id));
      return;
    }
    move(rfi, status);
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
        <ul className="mt-4 flex flex-col gap-4">
          {rfis.map((rfi) => (
            <li key={rfi.id} className="flex flex-col gap-1">
              <span className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-bold text-tx-primary">{rfi.subject}</span>
                <span className={`${pillClass} bg-panel-muted text-tx-secondary`}>{rfi.status}</span>
                {rfi.blocksFinalization && (
                  <span className={`${pillClass} bg-status-warning-soft text-status-warning`}>
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
              {rfi.answer && (
                <span className="rounded-md bg-panel-muted px-2.5 py-1.5 text-[12.5px] font-medium text-tx-primary leading-relaxed">
                  Answer: {rfi.answer}
                </span>
              )}

              {nextRfiStatuses(rfi.status).length > 0 && (
                <span className="mt-1 flex flex-wrap gap-1.5">
                  {nextRfiStatuses(rfi.status).map((status) => (
                    <button
                      key={status}
                      type="button"
                      disabled={busy}
                      onClick={() => advance(rfi, status)}
                      aria-expanded={status === "answered" ? answering === rfi.id : undefined}
                      className="rounded-md px-2.5 py-1 text-[12px] font-semibold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm disabled:opacity-50"
                    >
                      {ACTION_LABEL[status] ?? `Mark ${status}`}
                    </button>
                  ))}
                </span>
              )}

              {answering === rfi.id && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    const answer = String(new FormData(event.currentTarget).get("answer") ?? "").trim();
                    if (answer) move(rfi, "answered", answer);
                  }}
                  className="mt-2 flex flex-col gap-2"
                >
                  <textarea
                    name="answer"
                    required
                    rows={2}
                    placeholder="What the GC or architect answered"
                    aria-label={`Answer to ${rfi.rfiNumber}`}
                    className={inputClass}
                  />
                  <button
                    type="submit"
                    disabled={busy}
                    className="self-start rounded-md px-3 py-1.5 text-[12.5px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
                  >
                    {busy ? "Saving…" : "Save answer"}
                  </button>
                </form>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
