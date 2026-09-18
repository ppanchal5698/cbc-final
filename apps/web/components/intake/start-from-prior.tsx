"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { ClockCounterClockwise, PencilLine } from "@phosphor-icons/react";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { formatMoneyShort } from "@/lib/format";

interface Prior {
  id: string;
  code: string;
  name: string;
  brand?: string | null;
  architect?: string | null;
  gc?: string | null;
  quoteTotal?: number | null;
  lineCount?: number | null;
}

/**
 * The other two ways to start a bid (FR-11).
 *
 * Uploading a plan set is the first and the obvious one, so this only appears
 * while the bid has no documents: a repeat customer is usually a trim of the
 * last one, and an estimator who already knows the openings should not have to
 * upload anything to start typing them.
 */
export function StartFromPrior({
  code,
  documentCount,
}: {
  code: string;
  documentCount: number;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);

  const { data } = useSWR<{ priors: Prior[] }>(
    documentCount === 0 ? `/api/proxy/projects/${encodeURIComponent(code)}/prior-quotes` : null,
    proxyFetcher,
  );

  if (documentCount > 0) return null;
  const priors = data?.priors ?? [];

  async function reuse(prior: Prior) {
    setBusy(prior.code);
    try {
      await proxyMutate(
        `/api/proxy/projects/${encodeURIComponent(code)}/reuse/${encodeURIComponent(prior.code)}`,
        { method: "POST" },
      );
      toast.success(`Started from ${prior.code}`, { description: prior.name });
      router.refresh();
    } catch (problem) {
      toast.error("Could not start from that bid", { description: errorMessage(problem) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border border-subtle bg-panel shadow-1">
      <div className="flex items-center gap-2 border-b border-subtle px-5 py-3.5">
        <ClockCounterClockwise size={16} weight="duotone" className="text-brand-primary" />
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          Or start without a plan set
        </span>
      </div>

      <div className="px-5 py-4">
        {priors.length > 0 ? (
          <>
            <span className="block text-[13px] font-semibold text-tx-primary">
              Start from a past bid
            </span>
            <p className="mt-1 text-[12px] font-medium leading-relaxed text-tx-secondary">
              Same brand, architect or GC. The lines carry across and you trim what is different.
            </p>
            <ul className="mt-3 flex flex-col gap-1.5">
              {priors.slice(0, 4).map((prior) => (
                <li
                  key={prior.id}
                  className="flex items-center gap-3 rounded-lg border border-subtle bg-background px-3 py-2"
                >
                  <span className="flex min-w-0 flex-1 flex-col leading-tight">
                    <span className="truncate text-[12.5px] font-semibold text-tx-primary">
                      {prior.name}
                    </span>
                    <span className="truncate text-[11.5px] font-medium text-tx-muted">
                      {prior.code}
                      {prior.lineCount ? ` · ${prior.lineCount} lines` : ""}
                      {prior.quoteTotal ? ` · ${formatMoneyShort(prior.quoteTotal)}` : ""}
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => reuse(prior)}
                    disabled={busy !== null}
                    className="shrink-0 rounded-lg border border-subtle bg-panel px-3 py-1.5 text-[12px] font-bold text-tx-secondary transition-colors hover:text-tx-primary disabled:opacity-50"
                  >
                    {busy === prior.code ? "Starting…" : "Start from this"}
                  </button>
                </li>
              ))}
            </ul>
          </>
        ) : (
          <p className="text-[12.5px] font-medium leading-relaxed text-tx-secondary">
            No past bid for this brand, architect or GC to start from.
          </p>
        )}

        <a
          href={`/bids/${encodeURIComponent(code)}/extraction`}
          className="mt-4 flex items-center justify-center gap-2 rounded-lg border border-status-error/30 bg-status-error-soft px-4 py-2.5 text-[12.5px] font-bold text-status-error no-underline transition-colors hover:brightness-125"
        >
          <PencilLine size={15} weight="duotone" />
          Enter the openings by hand
        </a>
      </div>
    </section>
  );
}
