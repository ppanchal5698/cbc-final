import { describe, expect, it } from "vitest";

import {
  classifyJobError,
  isAdminRole,
  recordingUnavailableMessage,
  stageForJobType,
  translateJobError,
} from "./job-error";

describe("classifyJobError", () => {
  it("uses persisted errorCode when provided", () => {
    expect(classifyJobError("anything", "auth_failed")).toBe("auth_failed");
  });

  it("detects auth failures from message text", () => {
    expect(
      classifyJobError("Claude Code could not authenticate. Configure a provider on the settings screen."),
    ).toBe("auth_failed");
  });

  it("detects cli exit codes", () => {
    expect(classifyJobError("claude exited 1")).toBe("cli_exit");
  });

  it("detects timeouts and sync failures", () => {
    expect(classifyJobError("timed out after 1800s")).toBe("timeout");
    expect(classifyJobError("result sync failed: boom")).toBe("sync_failed");
  });
});

describe("translateJobError", () => {
  it("hides technical strings from estimators", () => {
    const result = translateJobError("claude exited 1", "estimator", { stage: "extraction" });
    expect(result?.title).toBe("Automatic read didn't finish");
    expect(result?.message).not.toContain("claude exited");
    expect(result?.technical).toBe("claude exited 1");
    expect(result?.actions.some((a) => a.label === "Add lines by hand")).toBe(true);
  });

  it("adds admin settings link for auth failures", () => {
    const result = translateJobError(
      "Claude Code could not authenticate. Configure a provider on the settings screen.",
      "admin",
      { stage: "extraction", errorCode: "auth_failed" },
    );
    expect(result?.actions.some((a) => a.href === "/settings")).toBe(true);
    expect(result?.message).toContain("Configure the provider");
  });

  it("words a pricing failure for pricing, not for a read", () => {
    // CBC-260001: a pricing job that failed its checks said "Automatic read
    // didn't finish ... try running the read again".
    const result = translateJobError(
      "artifact validation failed: test_bid: priced/line_items.json must contain a non-empty lines array",
      "admin",
      { errorCode: "artifact_validation", stage: stageForJobType("match_and_price") },
    );
    expect(result?.title).toBe("Pricing finished, but its output failed the checks");
    expect(result?.message).not.toMatch(/read/i);
    expect(result?.actions.some((a) => a.label === "Re-run pricing")).toBe(true);
  });

  it("recognises a validation failure from its text when no code was stored", () => {
    expect(classifyJobError("artifact validation failed: x")).toBe("artifact_validation");
  });

  it("maps each job type to its bid stage", () => {
    expect(stageForJobType("match_and_price")).toBe("quote");
    expect(stageForJobType("build_proposal")).toBe("proposal");
    expect(stageForJobType("rerun_extraction")).toBe("extraction");
  });

  it("routes estimators to notify admin for auth failures", () => {
    const result = translateJobError(
      "Claude Code could not authenticate.",
      "estimator",
      { errorCode: "auth_failed" },
    );
    expect(result?.actions.some((a) => a.label === "Notify your admin")).toBe(true);
    expect(result?.message).not.toContain("CLI");
  });
});

describe("isAdminRole", () => {
  it("recognises admin only", () => {
    expect(isAdminRole("admin")).toBe(true);
    expect(isAdminRole("estimator")).toBe(false);
  });
});

describe("recordingUnavailableMessage", () => {
  it("replaces legacy recording copy", () => {
    expect(
      recordingUnavailableMessage("This job ran before terminal recording existed."),
    ).toContain("Detailed logs aren't available");
  });
});
