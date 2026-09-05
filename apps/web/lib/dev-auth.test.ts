import { describe, expect, it, vi } from "vitest";

// dev-auth is `import "server-only"`, whose client build throws on import.
// Stubbing it is what lets the gate be tested at all - and it is the one
// function deciding whether the seed passwords reach a browser.
vi.mock("server-only", () => ({}));

import { isDevQuickLoginEnabled } from "./dev-auth";

// The seed passwords are in this repo. Whether they reach a browser is decided
// entirely by this function, so an unset APP_ENV must not read as development.
describe("isDevQuickLoginEnabled", () => {
  it("is off for every production-shaped APP_ENV", () => {
    for (const env of ["production", "PROD", " staging "]) {
      expect(isDevQuickLoginEnabled(env, "development")).toBe(false);
    }
  });

  it("is on when development is declared", () => {
    expect(isDevQuickLoginEnabled("development", "production")).toBe(true);
  });

  it("fails closed when APP_ENV is missing", () => {
    // A typoed or dropped variable used to enable the quick-login buttons.
    expect(isDevQuickLoginEnabled(undefined, "production")).toBe(false);
    expect(isDevQuickLoginEnabled("", "production")).toBe(false);
  });

  it("still works under next dev, where no build is emitted", () => {
    expect(isDevQuickLoginEnabled(undefined, "development")).toBe(true);
  });
});
