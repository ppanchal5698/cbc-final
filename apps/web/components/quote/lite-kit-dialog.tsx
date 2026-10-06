"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { LiteKitResponse } from "@/lib/types";

/**
 * NR-1: a lite kit, louver or glass priced off National Guard's size tables. The
 * server takes the cell the size falls in and NGP's multiplier; past the printed
 * table the line is a vendor quote. The estimator picks the table and the size.
 */
export function LiteKitDialog({
  code,
  groups,
  open,
  onOpenChange,
  onAdded,
}: {
  code: string;
  groups: string[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: () => void;
}) {
  const [table, setTable] = useState(0);
  const [size, setSize] = useState({ width: "", height: "" });
  const [qty, setQty] = useState("1");
  const [group, setGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const { data } = useSWR<LiteKitResponse>(open ? "/api/proxy/reference/lite-kit" : null, proxyFetcher);

  const tables = data?.data.tables ?? [];
  const chosen = tables[table];
  const width = Number(size.width);
  const height = Number(size.height);
  const ready = width > 0 && height > 0 && Boolean(chosen);

  async function add() {
    setBusy(true);
    try {
      const { line } = await proxyMutate<{ line: { costSourceDetail?: string } }>(
        `/api/proxy/projects/${encodeURIComponent(code)}/quote/lite-kits`,
        { body: { table, width, height, qty: Number(qty) || 1, ...(group ? { group } : {}) } },
      );
      toast.success("Lite kit added", { description: line.costSourceDetail });
      setSize({ width: "", height: "" });
      setQty("1");
      onOpenChange(false);
      onAdded();
    } catch (problem) {
      toast.error("Could not add the lite kit", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  const field = "rounded-md border border-subtle bg-background px-2 py-1.5 text-[12.5px] text-tx-primary";

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-w-[560px]">
        <DialogHeader>
          <DialogTitle>Add a lite kit</DialogTitle>
          <DialogDescription>
            Priced off National Guard&apos;s size table: an odd or fractional inch takes the next size up,
            and a size past the table goes out for a vendor quote.
          </DialogDescription>
        </DialogHeader>

        <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
          Table
          <select value={table} onChange={(event) => setTable(Number(event.target.value))} className={field}>
            {tables.map((entry, index) => (
              <option key={index} value={index}>
                p.{entry.printed_page ?? entry.pdf_page} - {entry.models}
              </option>
            ))}
          </select>
        </label>
        {chosen?.rules?.length ? (
          <ul className="list-disc pl-5 text-[11.5px] text-tx-muted">
            {chosen.rules.map((rule) => (
              <li key={rule}>{rule}</li>
            ))}
          </ul>
        ) : null}

        <div className="flex flex-wrap items-end gap-3">
          {(["width", "height"] as const).map((key) => (
            <label key={key} className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
              {key === "width" ? "Lite width (in)" : "Lite height (in)"}
              <input
                type="number"
                min={0}
                step="0.125"
                value={size[key]}
                onChange={(event) => setSize((current) => ({ ...current, [key]: event.target.value }))}
                className={`${field} w-28`}
              />
            </label>
          ))}
          <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
            Qty
            <input type="number" min={1} value={qty} onChange={(event) => setQty(event.target.value)} className={`${field} w-20`} />
          </label>
          {groups.length > 0 && (
            <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
              For
              <select value={group} onChange={(event) => setGroup(event.target.value)} className={field}>
                <option value="">—</option>
                {groups.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>

        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={busy}
            className="rounded-lg border border-subtle px-4 py-2 text-[13px] font-bold text-tx-secondary"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={add}
            disabled={busy || !ready}
            className="rounded-lg bg-brand-primary px-4 py-2 text-[13px] font-bold text-white disabled:opacity-50"
          >
            Price and add
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
