import { describe, expect, it } from "vitest";

import { nextRfqStatuses } from "@/lib/rfq";

describe("nextRfqStatuses", () => {
  it("follows the vendor RFQ state machine the API enforces", () => {
    expect(nextRfqStatuses("draft")).toEqual(["requested", "cancelled"]);
    expect(nextRfqStatuses("awaiting")).toEqual(["received", "expired", "cancelled"]);
    expect(nextRfqStatuses("received")).toEqual(["applied", "expired", "cancelled"]);
  });

  it("treats a missing status as a draft and offers nothing from a final or unknown one", () => {
    expect(nextRfqStatuses(undefined)).toEqual(["requested", "cancelled"]);
    expect(nextRfqStatuses("applied")).toEqual([]);
    expect(nextRfqStatuses("cancelled")).toEqual([]);
    expect(nextRfqStatuses("nonsense")).toEqual([]);
  });
});
