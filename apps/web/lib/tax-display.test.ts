import { describe, expect, it } from "vitest";

import { taxSummary } from "@/lib/tax-display";

describe("taxSummary", () => {
  it("returns a dollar amount when jurisdiction is known", () => {
    const result = taxSummary({ taxJurisdiction: "OH", tax: 12.5, taxRate: 0.07 });
    expect(result.value).toBe("$12.50");
    expect(result.hint).toBeNull();
    expect(result.muted).toBe(false);
  });

  it("returns a pending state when jurisdiction is missing", () => {
    const result = taxSummary({ taxJurisdiction: null, tax: 0 });
    expect(result.value).toBe("—");
    expect(result.hint).toContain("ship-to state");
    expect(result.muted).toBe(true);
  });
});
