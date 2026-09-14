import { describe, expect, it } from "vitest";

import { endpoints } from "@/lib/endpoints";

describe("endpoints", () => {
  it("builds job and settings paths", () => {
    expect(endpoints.jobRetry("abc123")).toBe("/api/proxy/jobs/abc123/retry");
    expect(endpoints.jobCancel("abc123")).toBe("/api/proxy/jobs/abc123/cancel");
    expect(endpoints.pipelineSettings()).toBe("/api/proxy/settings/pipeline");
    expect(endpoints.freshnessSettings()).toBe("/api/proxy/settings/freshness");
  });

  it("encodes the bid code it deletes", () => {
    expect(endpoints.projectDelete("CBC 1")).toBe("/api/proxy/projects/CBC%201");
  });
});
