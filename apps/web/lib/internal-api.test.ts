import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("server-only", () => ({}));

describe("assertProductionSecrets", () => {
  afterEach(() => {
    vi.resetModules();
    vi.unstubAllEnvs();
  });

  it("does not throw during the Next production build phase", async () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("NEXT_PHASE", "phase-production-build");
    const { assertProductionSecrets } = await import("./internal-api");
    expect(() => assertProductionSecrets()).not.toThrow();
  });

  it("throws at runtime when production still uses committed defaults", async () => {
    vi.stubEnv("APP_ENV", "production");
    vi.stubEnv("NEXT_PHASE", "phase-production-server");
    const { assertProductionSecrets } = await import("./internal-api");
    expect(() => assertProductionSecrets()).toThrow(/local-development defaults/);
  });

  it("allows development defaults when APP_ENV is development", async () => {
    vi.stubEnv("APP_ENV", "development");
    vi.stubEnv("NEXT_PHASE", "phase-production-server");
    const { assertProductionSecrets } = await import("./internal-api");
    expect(() => assertProductionSecrets()).not.toThrow();
  });
});
