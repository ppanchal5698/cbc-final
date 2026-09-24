"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { GridFour, Plus, X } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { CustomOtherMatrix } from "@/lib/types";

const URL = "/api/proxy/reference/custom-other-matrix";

/** The option lists, in the order an estimator reads them off a hardware set. */
const LISTS: Array<{ key: string; label: string; hint: string }> = [
  { key: "functions", label: "Functions", hint: "passage, privacy, storeroom…" },
  { key: "levers", label: "Lever designs", hint: "Apollo, Withnell…" },
  { key: "finishes", label: "Finishes", hint: "US3, US26D…" },
  { key: "backsets", label: "Backsets", hint: '2-3/4" (standard)…' },
  { key: "keyways", label: "Keyways", hint: "Schlage C, SFIC…" },
  { key: "strikes", label: "Strikes", hint: "ASA standard, T-strike…" },
  { key: "electrified", label: "Electrified options", hint: "electric strike, ELR…" },
  { key: "preps", label: "Preps", hint: "lead lined, 3/4 inch latchbolt…" },
  {
    key: "hard_manual_triggers",
    label: "Always priced by hand",
    hint: "what NR-13 refuses to automate",
  },
];

function ChipList({
  label,
  hint,
  items,
  busy,
  onAdd,
  onRemove,
}: {
  label: string;
  hint: string;
  items: string[];
  busy: boolean;
  onAdd: (value: string) => void;
  onRemove: (value: string) => void;
}) {
  const [draft, setDraft] = useState("");

  return (
    <div className="px-5 py-3.5">
      <div className="flex items-baseline justify-between gap-3">
        <h3 className="text-[12px] font-bold uppercase tracking-widest text-tx-muted">{label}</h3>
        <span className="text-[11px] font-medium text-tx-muted">{items.length}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {items.map((item) => (
          <span
            key={item}
            className="inline-flex items-center gap-1.5 rounded-full border border-subtle bg-panel-muted py-1 pl-3 pr-1.5 text-[12.5px] font-medium text-tx-primary"
          >
            {item}
            <button
              type="button"
              onClick={() => onRemove(item)}
              disabled={busy}
              aria-label={`Remove ${item} from ${label}`}
              className="rounded-full p-0.5 text-tx-muted hover:bg-status-error-soft hover:text-status-error transition-colors focus:ring-2 focus:ring-status-error"
            >
              <X size={12} weight="bold" />
            </button>
          </span>
        ))}
        {items.length === 0 && (
          <span className="text-[12.5px] font-medium text-tx-muted">Nothing listed.</span>
        )}
      </div>
      <form
        className="mt-2.5 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const value = draft.trim();
          if (!value) return;
          if (items.includes(value)) {
            toast.error(`${label} already lists "${value}"`);
            return;
          }
          onAdd(value);
          setDraft("");
        }}
      >
        <input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={hint}
          aria-label={`Add to ${label}`}
          disabled={busy}
          className="flex-1 rounded-md px-3 py-1.5 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
        />
        <button
          type="submit"
          disabled={busy || !draft.trim()}
          className="flex items-center gap-1 rounded-md px-3 py-1.5 text-[12.5px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
        >
          <Plus size={14} weight="bold" />
          Add
        </button>
      </form>
    </div>
  );
}

/**
 * The CUSTOM / OTHER option matrix.
 *
 * This was one textarea holding the whole document as JSON, which put nine
 * option lists and the NR-13 prose behind a parse error - and made "add one
 * keyway" a hand edit of a thousand-character blob.
 *
 * NR-13 is the point of the document: automate stock, then stop. Everything
 * listed here is an option that exists but is priced by hand, so the lists are
 * what an estimator maintains and the cost path is fixed at MANUAL.
 */
export function CustomOtherMatrixPanel() {
  const { data, error, isLoading, mutate } = useSWR<CustomOtherMatrix>(URL, proxyFetcher);
  const [busy, setBusy] = useState(false);

  const doc = useMemo(() => data ?? ({} as CustomOtherMatrix), [data]);

  async function save(key: string, values: string[], success: string) {
    setBusy(true);
    try {
      // Sent as the whole document with one list replaced, so the prose fields
      // and every other list survive the write untouched.
      await proxyMutate(URL, { method: "PUT", body: { data: { ...doc, [key]: values } } });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save the matrix", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function listFor(key: string): string[] {
    const value = (doc as Record<string, unknown>)[key];
    return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <GridFour size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">
            Custom / OTHER matrix
          </h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          {doc.design_principle ||
            "NR-13 — automate stock, then stop. These options exist but are priced by hand."}
        </p>
        {doc.cost_path && (
          <p className="mt-2 inline-flex items-center gap-1.5 rounded-md bg-panel-muted px-2.5 py-1 text-[11.5px] font-semibold text-tx-secondary">
            Cost path: {doc.cost_path}
          </p>
        )}
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the matrix: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">Loading…</p>
      )}

      {data && (
        <>
          <div className="divide-y divide-subtle flex-1 overflow-y-auto">
            {LISTS.map((list) => (
              <ChipList
                key={list.key}
                label={list.label}
                hint={list.hint}
                items={listFor(list.key)}
                busy={busy}
                onAdd={(value) =>
                  save(list.key, [...listFor(list.key), value], `${value} added to ${list.label}`)
                }
                onRemove={(value) =>
                  save(
                    list.key,
                    listFor(list.key).filter((item) => item !== value),
                    `${value} removed from ${list.label}`,
                  )
                }
              />
            ))}
          </div>
          {doc.keying_note && (
            <p className="border-t border-subtle px-5 py-3 text-[12px] font-medium text-tx-muted rounded-b-xl">
              {doc.keying_note}
            </p>
          )}
        </>
      )}
    </section>
  );
}
