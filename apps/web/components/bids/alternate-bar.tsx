"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus, Warning } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { formatMoneyShort } from "@/lib/format";

import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { AlternatesResponse } from "@/lib/types";

/**
 * Base bid and alternates as distinct, comparable groups.
 *
 * That comparability is the whole point: an estimator quotes the base and each
 * alternate separately so a GC can price the options against each other. How a
 * reconciliation actually resolves is still an open question with CBC, so this
 * shows the groups and says so rather than implying an answer.
 */
export function AlternateBar({
  code,
  active,
  onChange,
  showTotals = false,
}: {
  code: string;
  /** null = base bid; undefined = everything. */
  active: string | null | undefined;
  onChange: (next: string | null | undefined) => void;
  showTotals?: boolean;
}) {
  const [adding, setAdding] = useState(false);
  const { data, error, mutate } = useSWR<AlternatesResponse>(
    `/api/proxy/projects/${code}/alternates`,
    proxyFetcher,
  );

  const alternates = data?.alternates ?? [];

  if (error) {
    return (
      <FetchError
        title="Could not load alternates"
        error={error}
        onRetry={() => mutate()}
        compact
      />
    );
  }

  // With no alternates there is nothing to compare, so stay out of the way.
  if (alternates.length <= 1 && !adding) {
    return (
      <button
        onClick={() => setAdding(true)}
        className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-bold border border-dashed border-subtle text-tx-muted hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
      >
        <Plus size={14} weight="bold" />
        Add an alternate
      </button>
    );
  }

  async function create(name: string) {
    const trimmed = name.trim();
    if (!trimmed) return;
    try {
      await proxyMutate(`/api/proxy/projects/${code}/alternates`, { body: { name: trimmed } });
      toast.success(`${trimmed} created`, {
        description: "Empty by design — move lines into it, or add them by hand.",
      });
      setAdding(false);
      mutate();
    } catch (problem) {
      toast.error("Could not add that alternate", { description: errorMessage(problem) });
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl px-4 py-2.5 bg-panel border border-subtle shadow-sm">
      <span className="mr-2 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
        Groups
      </span>

      <button
        onClick={() => onChange(undefined)}
        className={`rounded-lg px-3 py-1.5 text-[12.5px] font-bold transition-all shadow-sm ${
          active === undefined
            ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
            : "bg-transparent text-tx-secondary hover:bg-panel-muted hover:text-tx-primary"
        }`}
      >
        All
      </button>

      {alternates.map((alternate) => {
        const on = active === alternate.name;
        return (
          <button
            key={alternate.label}
            onClick={() => onChange(alternate.name)}
            className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12.5px] font-bold transition-all shadow-sm ${
              on
                ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                : "bg-transparent border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary"
            }`}
          >
            {alternate.label}
            {showTotals ? (
              <span className={`tnum ${on ? "text-brand-primary/80" : "text-tx-muted"}`}>
                {alternate.grandTotal ? formatMoneyShort(alternate.grandTotal) : "—"}
              </span>
            ) : (
              <span className={`tnum ${on ? "text-brand-primary/80" : "text-tx-muted"}`}>
                {alternate.lineItemCount}
              </span>
            )}
          </button>
        );
      })}

      {adding ? (
        <form
          className="inline-flex"
          onSubmit={(event) => {
            event.preventDefault();
            const name = new FormData(event.currentTarget).get("name");
            if (typeof name === "string") create(name);
          }}
        >
          <input
            name="name"
            autoFocus
            placeholder="Alternate 1"
            onKeyDown={(event) => {
              if (event.key === "Escape") setAdding(false);
            }}
            onBlur={() => setAdding(false)}
            className="w-[140px] rounded-lg px-3 py-1.5 text-[12.5px] font-medium outline-none bg-panel-muted border border-brand-primary/30 text-tx-primary focus:ring-2 focus:ring-brand-border shadow-sm transition-all"
          />
        </form>
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="rounded-lg px-2.5 py-1.5 text-[12px] border border-dashed border-subtle text-tx-muted hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
        >
          <Plus size={14} weight="bold" />
        </button>
      )}

      <span className="flex-1" />

      <span
        className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-status-warning bg-status-warning-soft px-2.5 py-1 rounded-full shadow-sm"
        title={data?.pending}
      >
        <Warning size={14} weight="fill" />
        Reconciliation rules pending
      </span>
    </div>
  );
}
