import { describe, expect, it } from "vitest";

import { nextRfiStatuses, nextRfqStatuses } from "@/lib/rfq";

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

describe("nextRfiStatuses", () => {
  it("follows the RFI state machine the API enforces", () => {
    expect(nextRfiStatuses("open")).toEqual(["sent", "withdrawn"]);
    expect(nextRfiStatuses("sent")).toEqual(["answered", "withdrawn"]);
    expect(nextRfiStatuses("answered")).toEqual(["closed"]);
  });

  it("treats a missing status as open and offers nothing from a final or unknown one", () => {
    expect(nextRfiStatuses(null)).toEqual(["sent", "withdrawn"]);
    expect(nextRfiStatuses("closed")).toEqual([]);
    expect(nextRfiStatuses("withdrawn")).toEqual([]);
    expect(nextRfiStatuses("nonsense")).toEqual([]);
  });
});
