"use client";

import { useState } from "react";
import useSWR from "swr";
import { GridNine } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { FrpConstants } from "@/lib/types";
import { cn } from "@/lib/utils";

const FRP_URL = "/api/proxy/reference/frp-constants";

type FieldKey =
  | "panel_size"
  | "waste_pct"
  | "trim_stick_length"
  | "adhesive_coverage_sqft_per_unit"
  | "opening_handling";

const FIELDS: { key: FieldKey; label: string; numeric: boolean; noteKey: keyof FrpConstants; placeholder: string }[] = [
  { key: "panel_size", label: "Panel size", numeric: false, noteKey: "panel_size_note", placeholder: "4 x 8" },
  { key: "waste_pct", label: "Waste %", numeric: true, noteKey: "waste_pct_note", placeholder: "10" },
  { key: "trim_stick_length", label: "Trim stick length (ft)", numeric: true, noteKey: "trim_stick_length_note", placeholder: "8" },
  {
    key: "adhesive_coverage_sqft_per_unit",
    label: "Adhesive coverage (sq ft/unit)",
    numeric: true,
    noteKey: "adhesive_coverage_note",
    placeholder: "200",
  },
  { key: "opening_handling", label: "Opening handling", numeric: false, noteKey: "opening_handling_note", placeholder: "Deduct openings over 2 sq ft" },
];

/**
 * Enter the FRP geometry-to-quantity constants (Open Item 5). Until every one is
 * set the take-off reports geometry only and quantities stay null - a guessed
 * panel size or waste factor is a confidently wrong quote. Writes
 * reference-library/frp_constants/conversion_constants.json.
 */
export function FrpConstantsPanel() {
  const { data, error, isLoading, mutate } = useSWR<FrpConstants>(FRP_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<FrpConstants>(FRP_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that constant", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commit(key: FieldKey, numeric: boolean, raw: string, current: string | number | null) {
    const trimmed = raw.trim();
    if (numeric) {
      if (trimmed === "") {
        if (current === null) return;
        save({ [key]: null }, `${key} cleared`);
        return;
      }
      const next = Number(trimmed);
      if (Number.isNaN(next) || next < 0) {
        toast.error("Must be a number of 0 or more", { description: `Got "${raw}".` });
        mutate();
        return;
      }
      if (next === current) return;
      save({ [key]: next }, "Saved");
    } else {
      const value = trimmed || null;
      if (value === (current ?? null)) return;
      save({ [key]: value }, "Saved");
    }
  }

  const isSet = data?.status === "SET";

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2.5">
            <GridNine size={18} weight="bold" className="text-brand-primary" />
            <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">FRP conversion constants</h2>
          </div>
          {data && (
            <span
              className={cn(
                "rounded-full px-2.5 py-1 text-[11px] font-bold uppercase tracking-widest",
                isSet
                  ? "bg-status-success-soft text-status-success"
                  : "bg-status-warning-soft text-status-warning"
              )}
            >
              {isSet ? "Set" : "Pending"}
            </span>
          )}
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Geometry-to-quantity conversion for FRP panels. Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the constants: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && !isSet && (
        <p className="mx-5 mt-4 rounded-lg px-4 py-3 text-[12.5px] font-medium leading-relaxed bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm">
          Until every constant is set, the FRP take-off reports geometry only and leaves quantities
          null. It will not guess.
        </p>
      )}

      {data && (
        <div className="flex flex-col gap-4 p-5 flex-1 overflow-y-auto">
          {FIELDS.map((field) => {
            const current = data[field.key] as string | number | null;
            const note = data[field.noteKey] as string | undefined;
            return (
              <label key={field.key} className="flex flex-col gap-1.5">
                <span className="text-[12.5px] font-semibold text-tx-primary">{field.label}</span>
                <input
                  key={`${field.key}-${current ?? ""}`}
                  type={field.numeric ? "number" : "text"}
                  step={field.numeric ? "0.01" : undefined}
                  min={field.numeric ? "0" : undefined}
                  defaultValue={current ?? ""}
                  disabled={busy}
                  placeholder={field.placeholder}
                  aria-label={field.label}
                  onBlur={(event) => commit(field.key, field.numeric, event.target.value, current)}
                  className="rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
                />
                {note && (
                  <span className="text-[12px] font-medium text-tx-muted mt-0.5">
                    {note}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      )}
    </section>
  );
}
