import { describe, expect, it } from "vitest";

import { formatApiDetail, formatMoney, formatMoneyShort } from "@/lib/format";

describe("format", () => {
  it("formats currency with two decimals", () => {
    expect(formatMoney(1234.5)).toBe("1,234.50");
    expect(formatMoney(null)).toBe("—");
  });

  it("formats short money with dollar sign", () => {
    expect(formatMoneyShort(42000)).toBe("$42,000");
    expect(formatMoneyShort(undefined)).toBe("—");
  });

  it("flattens FastAPI validation arrays", () => {
    expect(formatApiDetail([{ msg: "field required" }, { msg: "invalid email" }])).toBe(
      "field required; invalid email",
    );
  });

  it("returns string detail as-is", () => {
    expect(formatApiDetail("Unauthorized")).toBe("Unauthorized");
  });
});
