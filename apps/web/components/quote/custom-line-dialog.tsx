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
import { customDescription, type CustomChoice, type CustomOtherMatrix } from "@/lib/custom-line";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";

type Single = "function" | "backset" | "finish" | "lever" | "keyway" | "strike";

const PICKS: { key: Single; label: string; from: "functions" | "backsets" | "finishes" | "levers" | "keyways" | "strikes" }[] = [
  { key: "function", label: "Function", from: "functions" },
  { key: "backset", label: "Backset", from: "backsets" },
  { key: "finish", label: "Finish", from: "finishes" },
  { key: "lever", label: "Lever", from: "levers" },
  { key: "keyway", label: "Keying", from: "keyways" },
  { key: "strike", label: "Strike", from: "strikes" },
];

const EMPTY: CustomChoice = { item: "Lockset", electrified: [], preps: [] };

/**
 * FR-9's custom tab: a line past the stock list, described from the CUSTOM /
 * OTHER matrix - function, backset, finish, lever, keying, strike, electrified
 * options and preps - and added to the quote for the estimator to price. The
 * matrix is there to describe a custom line precisely; nothing prices one.
 */
export function CustomLineDialog({
  code,
  open,
  onOpenChange,
  onAdded,
}: {
  code: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: () => void;
}) {
  const [choice, setChoice] = useState<CustomChoice>(EMPTY);
  const [qty, setQty] = useState("1");
  const [cost, setCost] = useState("");
  const [busy, setBusy] = useState(false);
  const { data: matrix } = useSWR<CustomOtherMatrix>(
    open ? "/api/proxy/reference/custom-other-matrix" : null,
    proxyFetcher,
  );

  const description = customDescription(choice);

  function pick(key: keyof CustomChoice, value: string) {
    setChoice((current) => ({ ...current, [key]: value || undefined }));
  }

  function toggle(key: "electrified" | "preps", value: string) {
    setChoice((current) => {
      const chosen = current[key] ?? [];
      return { ...current, [key]: chosen.includes(value) ? chosen.filter((v) => v !== value) : [...chosen, value] };
    });
  }

  async function add() {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${encodeURIComponent(code)}/quote/lines`, {
        body: {
          description,
          division: "08 71 00",
          qty: Number(qty) || 1,
          ...(cost.trim() ? { cost: Number(cost) } : {}),
          basis: "Custom / other - priced by hand",
        },
      });
      toast.success("Custom line added", {
        description: cost.trim() ? description : "Enter its cost on the quote.",
      });
      setChoice(EMPTY);
      setQty("1");
      setCost("");
      onOpenChange(false);
      onAdded();
    } catch (problem) {
      toast.error("Could not add the line", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  const field = "rounded-md border border-subtle bg-background px-2 py-1.5 text-[12.5px] text-tx-primary";

  return (
    <Dialog open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <DialogContent className="max-w-[640px]">
        <DialogHeader>
          <DialogTitle>Add a custom line</DialogTitle>
          <DialogDescription>
            Past the stock list: describe it from the custom / other options. You price it - the
            copilot does not.
          </DialogDescription>
        </DialogHeader>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
            Item
            <input value={choice.item} onChange={(event) => pick("item", event.target.value)} className={field} />
          </label>
          <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
            Manufacturer
            <input
              value={choice.manufacturer ?? ""}
              placeholder="e.g. Hager"
              onChange={(event) => pick("manufacturer", event.target.value)}
              className={field}
            />
          </label>
          {PICKS.map(({ key, label, from }) => (
            <label key={key} className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
              {label}
              <select
                value={choice[key] ?? ""}
                onChange={(event) => pick(key, event.target.value)}
                className={field}
              >
                <option value="">—</option>
                {matrix?.[from]?.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>

        {(["electrified", "preps"] as const).map((key) =>
          matrix?.[key]?.length ? (
            <fieldset key={key} className="mt-1">
              <legend className="text-[11.5px] font-semibold text-tx-muted">
                {key === "electrified" ? "Electrified" : "Preps and options"}
              </legend>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
                {matrix[key]!.map((option) => (
                  <label key={option} className="flex items-center gap-1.5 text-[12px] text-tx-secondary">
                    <input
                      type="checkbox"
                      checked={(choice[key] ?? []).includes(option)}
                      onChange={() => toggle(key, option)}
                    />
                    {option}
                  </label>
                ))}
              </div>
            </fieldset>
          ) : null,
        )}

        {matrix?.keying_note && <p className="text-[11.5px] text-tx-muted">{matrix.keying_note}</p>}

        <div className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
            Qty
            <input type="number" min={0} value={qty} onChange={(event) => setQty(event.target.value)} className={`${field} w-20`} />
          </label>
          <label className="flex flex-col gap-1 text-[11.5px] font-semibold text-tx-muted">
            Cost each (optional)
            <input
              type="number"
              min={0}
              step="0.01"
              value={cost}
              placeholder="priced by hand"
              onChange={(event) => setCost(event.target.value)}
              className={`${field} w-32`}
            />
          </label>
        </div>

        <p className="rounded-md bg-panel-muted px-3 py-2 text-[12px] font-semibold text-tx-primary">{description}</p>

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
            disabled={busy || !choice.item.trim()}
            className="rounded-lg bg-brand-primary px-4 py-2 text-[13px] font-bold text-white disabled:opacity-50"
          >
            Add to the quote
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
