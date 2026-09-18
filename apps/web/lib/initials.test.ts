import { describe, expect, it } from "vitest";

import { brandInitials, userInitials } from "@/lib/initials";

describe("userInitials", () => {
  it("prefers provided initials", () => {
    expect(userInitials("Admin User", "AD")).toBe("AD");
  });

  it("derives from name when initials are empty or missing", () => {
    expect(userInitials("Admin User", "")).toBe("AU");
    expect(userInitials("Admin User", null)).toBe("AU");
    expect(userInitials("Admin User", undefined)).toBe("AU");
  });

  it("does not throw when name is undefined", () => {
    expect(userInitials(undefined, undefined)).toBe("E");
    expect(userInitials(null, null)).toBe("E");
  });
});

describe("brandInitials", () => {
  it("handles null brand", () => {
    expect(brandInitials(null)).toBe("U");
    expect(brandInitials(undefined)).toBe("U");
  });
});
