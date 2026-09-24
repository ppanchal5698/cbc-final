"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Table } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { LiteKitDoc, LiteKitResponse, LiteKitTable } from "@/lib/types";

const URL = "/api/proxy/reference/lite-kit";

/** Numeric sort: the keys arrive as strings, so "10" must not sort before "4". */
function sizes(record: Record<string, unknown> | undefined): number[] {
  return Object.keys(record ?? {})
    .map(Number)
    .filter((n) => Number.isFinite(n))
    .sort((a, b) => a - b);
}

/**
 * National Guard lite-kit and louver list prices, as the width x height grid
 * they actually are.
 *
 * This was a textarea holding the entire document - twenty tables and several
 * thousand prices - as raw JSON. Changing one cell meant editing JSON by hand
 * with every other table one keystroke away, and a parse error threw the edit
 * away with "must be valid JSON". Cells are now edited individually and the
 * document is rebuilt around the change, so nothing else can move.
 *
 * Prices are list, not cost: the NGP vendor multiplier is applied downstream.
 */
export function LiteKitPanel() {
  const { data, error, isLoading, mutate } = useSWR<LiteKitResponse>(URL, proxyFetcher);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);

  const doc: LiteKitDoc = useMemo(() => data?.data ?? {}, [data]);
  const tables = useMemo(() => doc.tables ?? [], [doc]);

  useEffect(() => {
    if (index >= tables.length) setIndex(0);
  }, [tables.length, index]);

  const table: LiteKitTable | undefined = tables[index];
  const heights = sizes(table?.prices);
  const widths = useMemo(() => {
    const seen = new Set<number>();
    for (const row of Object.values(table?.prices ?? {})) {
      for (const width of sizes(row)) seen.add(width);
    }
    return [...seen].sort((a, b) => a - b);
  }, [table]);

  async function commit(height: number, width: number, raw: string, current: number | undefined) {
    const next = Number(raw);
    if (raw.trim() === "") {
      mutate();
      return;
    }
    if (Number.isNaN(next) || next < 0) {
      toast.error("A list price is a number, zero or above", { description: `Got "${raw}".` });
      mutate();
      return;
    }
    const rounded = Math.round(next * 100) / 100;
    if (rounded === current) return;

    setBusy(true);
    try {
      // One cell, addressed by table and size. Posting the whole document back -
      // which is what this panel used to do - means two people editing different
      // tables overwrite each other, and the audit entry can only say that
      // something in the document changed.
      await proxyMutate(URL, {
        method: "PATCH",
        body: { table: index, width, height, price: rounded },
      });
      toast.success(`${width}" × ${height}" set to $${rounded.toFixed(2)}`);
      mutate();
    } catch (problem) {
      toast.error("Could not save that price", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Table size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Lite-kit prices</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          National Guard list prices by width × height. {doc.sizing_rule || "Odd and fractional sizes take the next largest cell."}
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the lite-kit tables: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">Loading…</p>
      )}

      {data && (
        <>
          <div className="border-b border-subtle px-5 py-3 flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1.5 min-w-0 flex-1">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Table ({tables.length} on file)
              </span>
              <select
                className="w-full rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
                value={index}
                onChange={(event) => setIndex(Number(event.target.value))}
                disabled={busy}
                aria-label="Lite-kit table"
              >
                {tables.map((entry, position) => (
                  <option key={position} value={position}>
                    {entry.models || `Table ${position + 1}`}
                    {entry.pdf_page ? ` — page ${entry.pdf_page}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-[12px] font-medium text-tx-secondary">
              {widths.length} widths × {heights.length} heights
            </p>
          </div>

          {(table?.rules?.length ?? 0) > 0 && (
            <ul className="border-b border-subtle px-5 py-3 space-y-1">
              {table?.rules?.map((rule) => (
                <li key={rule} className="text-[12.5px] font-medium text-tx-secondary">
                  • {rule}
                </li>
              ))}
            </ul>
          )}

          <div className="flex-1 overflow-auto px-5 py-3">
            {heights.length === 0 ? (
              <p className="text-[13px] font-medium text-tx-muted">This table has no priced cells.</p>
            ) : (
              <table className="border-collapse">
                <thead>
                  <tr>
                    <th className="sticky left-0 z-10 bg-panel px-2 py-1.5 text-left text-[10px] font-bold uppercase tracking-widest text-tx-muted">
                      H \ W
                    </th>
                    {widths.map((width) => (
                      <th
                        key={width}
                        className="px-2 py-1.5 text-right text-[11px] font-bold text-tx-secondary"
                        scope="col"
                      >
                        {width}&quot;
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {heights.map((height) => (
                    <tr key={height} className="hover:bg-panel-muted transition-colors">
                      <th
                        scope="row"
                        className="sticky left-0 z-10 bg-panel px-2 py-1 text-left text-[11px] font-bold text-tx-secondary"
                      >
                        {height}&quot;
                      </th>
                      {widths.map((width) => {
                        const value = table?.prices?.[String(height)]?.[String(width)];
                        return (
                          <td key={width} className="px-0.5 py-0.5">
                            <input
                              key={`${index}-${height}-${width}-${value ?? ""}`}
                              type="number"
                              step="1"
                              min="0"
                              defaultValue={value ?? ""}
                              disabled={busy}
                              aria-label={`List price, ${width} inch by ${height} inch`}
                              onBlur={(event) => commit(height, width, event.target.value, value)}
                              className="tnum w-[68px] rounded px-1.5 py-1 text-right text-[12px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors"
                            />
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {doc.note && (
            <p className="border-t border-subtle px-5 py-3 text-[12px] font-medium text-tx-muted rounded-b-xl">
              {doc.note}
            </p>
          )}
        </>
      )}
    </section>
  );
}
