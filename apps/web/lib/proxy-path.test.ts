import { describe, expect, it } from "vitest";

import { buildProxyTarget, rejectUnsafeProxySegments } from "./proxy-path";
import { safeRedirectPath } from "./safe-redirect";

describe("rejectUnsafeProxySegments", () => {
  it("rejects parent segments", () => {
    expect(rejectUnsafeProxySegments(["projects", "..", "admin"])).toMatch(/traversal/);
  });

  it("rejects encoded separators inside a segment", () => {
    expect(rejectUnsafeProxySegments(["x%2F..%2F..%2Fadmin"])).toMatch(/encoded/);
  });

  it("allows normal api paths", () => {
    expect(rejectUnsafeProxySegments(["projects", "BID-001", "documents"])).toBeNull();
  });
});

describe("buildProxyTarget", () => {
  it("keeps requests under /api after normalisation", () => {
    const target = buildProxyTarget("http://api:8001", ["projects", "BID-001"]);
    expect(target.pathname).toBe("/api/projects/BID-001");
  });

  it("throws when normalisation escapes /api", () => {
    expect(() =>
      buildProxyTarget("http://api:8001", ["x", "..", "..", "admin", "whatever"]),
    ).toThrow(/escaped/);
  });
});

describe("safeRedirectPath", () => {
  it("allows in-app paths", () => {
    expect(safeRedirectPath("/bids/ABC-001/extraction")).toBe("/bids/ABC-001/extraction");
  });

  it("blocks protocol-relative URLs", () => {
    expect(safeRedirectPath("//evil.com")).toBe("/dashboard");
  });

  it("blocks backslash open redirects", () => {
    expect(safeRedirectPath("/\\/evil.com")).toBe("/dashboard");
  });
});
