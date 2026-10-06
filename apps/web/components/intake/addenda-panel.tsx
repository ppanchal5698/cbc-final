"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FilePlus, Files } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { Addendum } from "@/lib/types";

type Field = "issuedOn" | "changedDocuments" | "newBidDue" | "changedForms";

function day(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "";
}

/**
 * The addendum log (FR-14): each addendum by number, the day it was issued, the
 * drawings and specs it changed, a moved bid date and the bid forms it changed.
 * An uploaded addendum PDF logs itself; one announced by phone or email is
 * logged here. A new bid date moves the bid's, and the proposal acknowledges
 * every addendum by number.
 */
export function AddendaPanel({ code, addenda }: { code: string; addenda: Addendum[] }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  async function log() {
    setBusy(true);
    try {
      const entry = await proxyMutate<Addendum>(`/api/proxy/projects/${encodeURIComponent(code)}/addenda`, {
        body: {},
      });
      toast.success(`Addendum ${entry.number} logged`, { description: "Add the date it was issued and what it changed." });
      router.refresh();
    } catch (problem) {
      toast.error("Could not log the addendum", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function save(addendum: Addendum, field: Field, value: string) {
    const current = field === "issuedOn" || field === "newBidDue" ? day(addendum[field]) : (addendum[field] ?? "");
    if (value.trim() === current) return;
    try {
      await proxyMutate(`/api/proxy/projects/${encodeURIComponent(code)}/addenda/${addendum.number}`, {
        method: "PATCH",
        body: { [field]: value.trim() || null },
      });
      if (field === "newBidDue" && value) toast.success("Bid date moved", { description: `Now due ${value}` });
      router.refresh();
    } catch (problem) {
      toast.error("Could not save that", { description: errorMessage(problem) });
    }
  }

  const cell = "rounded border border-subtle bg-background px-1.5 py-1 text-[12px] text-tx-primary";

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="flex items-center gap-3 border-b border-subtle px-5 py-4">
        <Files size={18} weight="fill" className="text-brand-primary" />
        <span className="text-[16px] font-bold tracking-tight">Addenda</span>
        <span className="flex-1" />
        <button
          onClick={log}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[12px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary disabled:opacity-50 transition-colors shadow-sm"
        >
          <FilePlus size={14} weight="bold" />
          Log an addendum
        </button>
      </div>

      {addenda.length === 0 ? (
        <p className="px-5 py-4 text-[12.5px] font-medium text-tx-muted">
          None logged. Upload an addendum PDF as &ldquo;Addendum&rdquo;, or log one the GC announced by
          phone or email. The proposal acknowledges each by number.
        </p>
      ) : (
        <div className="overflow-x-auto px-5 py-3">
          <table className="w-full min-w-[640px] text-[12px]">
            <thead>
              <tr className="text-left text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                <th className="py-1.5 pr-2">No.</th>
                <th className="py-1.5 pr-2">Issued</th>
                <th className="py-1.5 pr-2">Drawings and specs changed</th>
                <th className="py-1.5 pr-2">New bid date</th>
                <th className="py-1.5 pr-2">Forms changed</th>
              </tr>
            </thead>
            <tbody>
              {addenda.map((addendum) => (
                <tr key={addendum.number} className="border-t border-subtle align-top">
                  <td className="py-2 pr-2 font-bold text-tx-primary">
                    {addendum.number}
                    {addendum.filename && (
                      <span className="block text-[10.5px] font-medium text-tx-muted" title={addendum.filename}>
                        {addendum.version ? `v${addendum.version}` : "PDF"}
                      </span>
                    )}
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="date"
                      aria-label={`Addendum ${addendum.number} issued`}
                      defaultValue={day(addendum.issuedOn)}
                      onBlur={(event) => save(addendum, "issuedOn", event.target.value)}
                      className={cell}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      aria-label={`Addendum ${addendum.number} drawings and specs changed`}
                      defaultValue={addendum.changedDocuments ?? ""}
                      placeholder="e.g. A601, A602; 08 71 00"
                      onBlur={(event) => save(addendum, "changedDocuments", event.target.value)}
                      className={`${cell} w-full`}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      type="date"
                      aria-label={`Addendum ${addendum.number} new bid date`}
                      defaultValue={day(addendum.newBidDue)}
                      onBlur={(event) => save(addendum, "newBidDue", event.target.value)}
                      className={cell}
                      title={addendum.previousBidDue ? `Was due ${day(addendum.previousBidDue)}` : undefined}
                    />
                  </td>
                  <td className="py-2 pr-2">
                    <input
                      aria-label={`Addendum ${addendum.number} forms changed`}
                      defaultValue={addendum.changedForms ?? ""}
                      placeholder="none"
                      onBlur={(event) => save(addendum, "changedForms", event.target.value)}
                      className={`${cell} w-full`}
                    />
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
