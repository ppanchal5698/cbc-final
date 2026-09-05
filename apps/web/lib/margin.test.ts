import { describe, expect, it } from "vitest";

import { belowBandCount, belowBandTitle, isBelowBand } from "@/lib/margin";
import type { QuoteLine } from "@/lib/types";

const line = (marginCheck: QuoteLine["marginCheck"]): QuoteLine => ({
  id: "1",
  projectId: "p1",
  description: "Hager 3400 lockset",
  qty: 1,
  cost: 100,
  margin: 0.22,
  sell: 128.2,
  extended: 128.2,
  addedByHand: false,
  marginOverridden: false,
  flags: [],
  marginCheck,
});

describe("below-band margin", () => {
  it("reads the API's verdict rather than re-deriving the floor", () => {
    expect(isBelowBand(line({ status: "fail", flag: "below_band" }))).toBe(true);
    expect(isBelowBand(line({ status: "pass", flag: null }))).toBe(false);
  });

  it("treats an unpriced or unknown line as not below band", () => {
    expect(isBelowBand(line({ status: "unpriced" }))).toBe(false);
    expect(isBelowBand(line({ status: "unknown_product_type" }))).toBe(false);
    expect(isBelowBand(line(null))).toBe(false);
    expect(isBelowBand(line(undefined))).toBe(false);
  });

  it("explains the shortfall when the API sent the numbers", () => {
    const title = belowBandTitle(
      line({ status: "fail", flag: "below_band", floor: 0.35, applied_margin: 0.22, product_type: "partitions" }),
    );
    expect(title).toContain("22%");
    expect(title).toContain("35%");
    expect(title).toContain("partitions");
  });

  it("still says something useful when it did not", () => {
    expect(belowBandTitle(line({ status: "fail", flag: "below_band" }))).toContain("NFR-8");
  });

  it("counts across every line it is given", () => {
    expect(
      belowBandCount([
        line({ status: "fail", flag: "below_band" }),
        line({ status: "pass", flag: null }),
        line({ status: "fail", flag: "below_band" }),
      ]),
    ).toBe(2);
  });
});
