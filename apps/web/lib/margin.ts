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

/**
 * Whether a margin about to be typed onto this line would land under its floor.
 *
 * Reads the floor from the API's own verdict on the line, so the grid asks for
 * a reason exactly where the review would raise a blocking `margin` flag. A
 * line the API has not checked has no floor to compare against.
 */
export function wouldBeBelowBand(line: QuoteLine, margin: number | null): boolean {
  const floor = line.marginCheck?.floor;
  // Same tolerance as calc.validate_margin, so a margin typed at the floor is not asked about.
  return margin !== null && floor !== undefined && margin < floor - 1e-9;
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
