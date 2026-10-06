"use client";

import { useState } from "react";
import useSWR from "swr";
import { Info, Plus, Warning } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { formatMoney, formatMoneyShort } from "@/lib/format";

import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { Alternate, AlternateKind, AlternatesResponse } from "@/lib/types";

const KINDS: { key: Exclude<AlternateKind, "by_others">; label: string; short: string }[] = [
  { key: "additive", label: "Add", short: "add" },
  { key: "deductive", label: "Deduct", short: "deduct" },
  { key: "substitution", label: "Substitution", short: "sub" },
];

function signed(value: number | undefined): string {
  if (value === undefined) return "—";
  return `${value < 0 ? "−" : "+"}${formatMoneyShort(Math.abs(value))}`;
}

/**
 * Base bid and alternates as distinct, comparable groups (FR-14).
 *
 * That comparability is the whole point: an estimator quotes the base and each
 * alternate separately so a GC can price the options against each other. Each
 * alternate says what kind it is and what accepting it does to the base bid; the
 * selected one shows its take-off - base quantity, with the alternate, and the
 * difference - and any base line another alternate also takes out.
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
  const [kind, setKind] = useState<Exclude<AlternateKind, "by_others">>("additive");
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
      await proxyMutate(`/api/proxy/projects/${code}/alternates`, { body: { name: trimmed, kind } });
      toast.success(`${trimmed} created`, {
        description:
          kind === "deductive"
            ? "Move into it the base scope it deletes - it stays in the base bid."
            : kind === "substitution"
              ? "Move into it what it offers, and mark the base lines it replaces."
              : "Empty by design — move lines into it, or add them by hand.",
      });
      setAdding(false);
      mutate();
    } catch (problem) {
      toast.error("Could not add that alternate", { description: errorMessage(problem) });
    }
  }

  async function describe(alternate: Alternate, change: Partial<Pick<Alternate, "kind" | "priority" | "description">>) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/alternates/${encodeURIComponent(alternate.name ?? "")}`, {
        method: "PATCH",
        body: change,
      });
      mutate();
    } catch (problem) {
      toast.error("Could not change that alternate", { description: errorMessage(problem) });
    }
  }

  const selected = alternates.find((entry) => !entry.isBase && entry.name === active && entry.kind !== "by_others");
  const overlaps = data?.overlaps ?? [];

  return (
    <div className="flex flex-col gap-2 rounded-xl px-4 py-2.5 bg-panel border border-subtle shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
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
          const offered = !alternate.isBase && alternate.kind !== "by_others";
          return (
            <button
              key={alternate.label}
              onClick={() => onChange(alternate.name)}
              title={alternate.description ?? undefined}
              className={`flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12.5px] font-bold transition-all shadow-sm ${
                on
                  ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                  : "bg-transparent border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary"
              }`}
            >
              {alternate.label}
              {offered && (
                <span className="text-[10px] font-bold uppercase tracking-wider text-tx-muted">
                  {KINDS.find((entry) => entry.key === alternate.kind)?.short ?? "add"}
                </span>
              )}
              {showTotals ? (
                <span className={`tnum ${on ? "text-brand-primary/80" : "text-tx-muted"}`}>
                  {offered
                    ? signed(alternate.net)
                    : alternate.grandTotal
                      ? formatMoneyShort(alternate.grandTotal)
                      : "—"}
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
            className="inline-flex items-center gap-1.5"
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
              className="w-[140px] rounded-lg px-3 py-1.5 text-[12.5px] font-medium outline-none bg-panel-muted border border-brand-primary/30 text-tx-primary focus:ring-2 focus:ring-brand-border shadow-sm transition-all"
            />
            <select
              aria-label="Kind of alternate"
              value={kind}
              onChange={(event) => setKind(event.target.value as typeof kind)}
              className="rounded-lg border border-subtle bg-panel-muted px-2 py-1.5 text-[12px] font-medium text-tx-secondary"
            >
              {KINDS.map((entry) => (
                <option key={entry.key} value={entry.key}>
                  {entry.label}
                </option>
              ))}
            </select>
            <button type="submit" className="rounded-lg px-2.5 py-1.5 text-[12px] font-bold text-brand-primary">
              Add
            </button>
            <button type="button" onClick={() => setAdding(false)} className="px-1.5 text-[12px] text-tx-muted">
              Cancel
            </button>
          </form>
        ) : (
          <button
            onClick={() => setAdding(true)}
            aria-label="Add an alternate"
            className="rounded-lg px-2.5 py-1.5 text-[12px] border border-dashed border-subtle text-tx-muted hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
          >
            <Plus size={14} weight="bold" />
          </button>
        )}

        <span className="flex-1" />

        <span title={data?.pending} className="flex items-center gap-1.5 text-[11px] font-medium text-tx-muted">
          <Info size={14} weight="fill" />
          Before tax and freight
        </span>
      </div>

      {selected && (
        <div className="flex flex-col gap-2 border-t border-subtle pt-2 text-[12px]">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-tx-muted">
              Kind
              <select
                value={selected.kind ?? "additive"}
                onChange={(event) => describe(selected, { kind: event.target.value as AlternateKind })}
                className="rounded border border-subtle bg-background px-1.5 py-0.5 font-medium text-tx-secondary"
              >
                {KINDS.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-tx-muted">
              Priority
              <input
                type="number"
                min={1}
                max={99}
                defaultValue={selected.priority ?? undefined}
                key={`${selected.name}-${selected.priority}`}
                onBlur={(event) => {
                  const next = Number(event.target.value);
                  if (next && next !== selected.priority) describe(selected, { priority: next });
                }}
                className="w-14 rounded border border-subtle bg-background px-1.5 py-0.5 text-tx-secondary"
              />
            </label>
            <input
              placeholder="What the bid form says it is"
              defaultValue={selected.description ?? ""}
              key={`${selected.name}-description`}
              onBlur={(event) => {
                const next = event.target.value.trim();
                if (next !== (selected.description ?? "")) describe(selected, { description: next || null });
              }}
              className="min-w-[220px] flex-1 rounded border border-subtle bg-background px-2 py-0.5 text-tx-secondary"
            />
            <span className="tnum font-semibold text-tx-primary">
              {selected.complete === false
                ? "Price still to come"
                : `${(selected.net ?? 0) < 0 ? "Deduct" : "Add"} $${formatMoney(Math.abs(selected.net ?? 0))} · base bid with it $${formatMoney(selected.withBase)}`}
            </span>
          </div>
          {!!selected.takeoff?.length && (
            <table className="w-full max-w-[560px] text-[11.5px]">
              <thead>
                <tr className="text-left text-tx-muted">
                  <th className="font-semibold">Item</th>
                  <th className="text-right font-semibold">Base</th>
                  <th className="text-right font-semibold">With it</th>
                  <th className="text-right font-semibold">Difference</th>
                </tr>
              </thead>
              <tbody>
                {selected.takeoff.map((row, index) => (
                  <tr key={`${row.item}-${index}`} className="text-tx-secondary">
                    <td className="truncate">{row.item ?? "—"}</td>
                    <td className="tnum text-right">{row.baseQty}</td>
                    <td className="tnum text-right">{row.withAlternateQty}</td>
                    <td className="tnum text-right">{row.netQty > 0 ? `+${row.netQty}` : row.netQty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {overlaps.length > 0 && (
        <p className="flex items-start gap-2 rounded-lg bg-status-warning-soft px-3 py-2 text-[12px] font-medium text-status-warning">
          <Warning size={14} weight="fill" className="mt-0.5 shrink-0" />
          {overlaps
            .map((overlap) => `${overlap.line ?? "A line"} is taken out by ${overlap.alternates.join(" and ")}`)
            .join("; ")}
          . Accepted together, it comes out once.
        </p>
      )}
    </div>
  );
}
