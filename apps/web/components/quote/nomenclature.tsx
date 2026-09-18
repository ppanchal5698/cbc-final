"use client";

import { useState } from "react";
import { FloppyDisk } from "@phosphor-icons/react";
import { toast } from "sonner";

import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";

/**
 * Compose an opening's nomenclature and keep it as a catalog part.
 *
 * These four choices are how CBC writes an opening on a quote. They are inputs
 * to "Save to catalog" - a compose form, not bid state: nothing here is stored
 * against the bid, and the copy says so, because a form that looked saved and
 * was not would be worse than no form.
 */
const FIELDS = [
  {
    key: "size",
    label: "Size",
    options: ["2-8 x 6-8", "3-0 x 6-8", "3-0 x 7-0", "3-6 x 7-0", "6-0 x 7-0", "6-0 x 8-0"],
  },
  {
    key: "finish",
    label: "Finish",
    options: [
      "US26D satin chrome",
      "US32D satin stainless",
      "US10B oil-rubbed bronze",
      "US4 satin brass",
      "Matte black",
      "Primed for paint",
    ],
  },
  {
    key: "prep",
    label: "Hardware prep",
    options: [
      "Cylindrical prep",
      "Mortise prep",
      "SVR reinforced prep",
      "Exit device prep",
      "Deadbolt prep",
      "No prep — blank",
    ],
  },
  {
    key: "fab",
    label: "Fabrication instruction",
    options: [
      "Knock-down frame, 5-5/8 wall",
      "Knock-down frame, 5-7/8 wall",
      "Welded frame, 5-3/4 wall",
      "Welded frame with side lights",
      "Laminated door with custom finish",
      "Field-verify before release",
    ],
  },
] as const;

type Values = Record<(typeof FIELDS)[number]["key"], string>;

export function Nomenclature({ opening, division }: { opening: string; division: string }) {
  const [values, setValues] = useState<Values>(() => ({
    size: FIELDS[0].options[2],
    finish: FIELDS[1].options[0],
    prep: FIELDS[2].options[0],
    fab: FIELDS[3].options[0],
  }));
  const [busy, setBusy] = useState(false);

  async function saveToCatalog() {
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/catalog/products", {
        method: "POST",
        body: {
          part: `CBC-${opening}-${values.size.replace(/[^0-9A-Za-z]/g, "")}`,
          description: `${values.prep} — ${values.size} — ${values.finish} — ${values.fab}`,
          manufacturer: "CBC fabrication",
          division,
          availability: "Made to order",
        },
      });
      toast.success("Saved to the catalog", {
        description: `Opening ${opening} nomenclature is reusable`,
      });
    } catch (problem) {
      toast.error("Could not save to the catalog", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-b border-subtle/50 bg-background px-5 py-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {FIELDS.map((field) => (
          <label key={field.key} className="flex flex-col gap-1">
            <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
              {field.label}
            </span>
            <select
              value={values[field.key]}
              disabled={busy}
              onChange={(event) =>
                setValues((current) => ({ ...current, [field.key]: event.target.value }))
              }
              className="rounded-lg border border-subtle bg-panel px-2.5 py-1.5 text-[12.5px] font-medium text-tx-primary outline-none focus:border-brand-primary/30 focus:ring-2 focus:ring-brand-border"
            >
              {field.options.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={saveToCatalog}
          disabled={busy}
          className="flex items-center gap-1.5 rounded-lg border border-subtle bg-panel px-3 py-1.5 text-[12px] font-bold text-tx-secondary shadow-1 transition-colors hover:bg-panel-muted hover:text-tx-primary disabled:opacity-50"
        >
          <FloppyDisk size={14} weight="duotone" />
          {busy ? "Saving…" : "Save to catalog"}
        </button>
        <span className="text-[11.5px] font-medium text-tx-muted">
          Makes a reusable part from this description. It is not saved on the bid.
        </span>
      </div>
    </div>
  );
}
