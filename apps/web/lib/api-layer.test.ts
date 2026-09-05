import { describe, expect, it } from "vitest";

import { swrKeys } from "@/lib/swr-keys";
import { endpoints } from "@/lib/endpoints";

describe("swr-keys", () => {
  it("builds project list keys with filters", () => {
    expect(swrKeys.projects({ limit: 50, q: "acme" })).toBe(
      "/api/proxy/projects?limit=50&q=acme",
    );
  });

  it("builds job keys with encoded project code", () => {
    expect(swrKeys.jobs("bid_12", 1)).toBe("/api/proxy/jobs?project=bid_12&limit=1");
  });
});

describe("endpoints", () => {
  it("builds cancel and pipeline paths", () => {
    expect(endpoints.jobRetry("abc123")).toBe("/api/proxy/jobs/abc123/retry");
    expect(endpoints.jobsDead()).toBe("/api/proxy/jobs/dead");
    expect(endpoints.pipelineSettings()).toBe("/api/proxy/settings/pipeline");
    expect(endpoints.freshnessSettings()).toBe("/api/proxy/settings/freshness");
  });
});
