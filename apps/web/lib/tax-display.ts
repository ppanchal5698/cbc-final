import { formatMoney } from "@/lib/format";

export type TaxTotals = {
  taxJurisdiction?: string | null;
  tax?: number | null;
  taxRate?: number | null;
};

export type TaxSummary = {
  label: string;
  value: string;
  hint: string | null;
  muted: boolean;
};

/** Present tax as a resolved amount or a pending state — never a bare UNRESOLVED warning. */
export function taxSummary(totals: TaxTotals): TaxSummary {
  if (totals.taxJurisdiction) {
    const rate =
      totals.taxRate != null
        ? `${(totals.taxRate * 100).toFixed(3).replace(/0+$/, "").replace(/\.$/, "")}%`
        : "";
    return {
      label: rate ? `Tax ${rate}` : "Sales tax",
      value: `$${formatMoney(totals.tax ?? 0)}`,
      hint: null,
      muted: false,
    };
  }

  return {
    label: "Sales tax",
    value: "—",
    hint: "Add ship-to state on Intake to calculate OH/KY tax",
    muted: true,
  };
}
