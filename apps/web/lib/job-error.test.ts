import { describe, expect, it } from "vitest";

import {
  classifyJobError,
  isAdminRole,
  recordingUnavailableMessage,
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
