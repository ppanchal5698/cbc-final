import { formatPercent } from "@/lib/format";
import type { QuoteLine } from "@/lib/types";

/**
 * Whether this line's margin fell under its product-type floor (NFR-8).
 *
 * The API decides: `calc.validate_margin` sets `flag: "below_band"`, and the
 * floor comes from the margin sheet. The screen reads the verdict rather than
 * re-deriving it, so the bands have one implementation and the badge cannot
 * disagree with the quote.
 *
 * This was computed on every line by `services/quote.py` and then dropped at the
 * UI boundary - the one guardrail that exists to make below-band pricing visible
 * was visible to nobody.
 */
export function isBelowBand(line: QuoteLine): boolean {
  return line.marginCheck?.flag === "below_band";
}

/** The hover text explaining what the badge is claiming. */
export function belowBandTitle(line: QuoteLine): string {
  const check = line.marginCheck;
  if (!check || check.floor === undefined || check.applied_margin === undefined) {
    return "Margin is below its band floor (NFR-8)";
  }
  return (
    `${formatPercent(check.applied_margin)} applied against a ` +
    `${formatPercent(check.floor)} floor for ${check.product_type ?? "this type"}. ` +
    "Flagged only - approval routing is deferred (NFR-8)."
  );
}

/** How many of these lines are below band. Counted over all lines, never a filtered view. */
export function belowBandCount(lines: QuoteLine[]): number {
  return lines.filter(isBelowBand).length;
}
