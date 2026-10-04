/** Stable codes persisted by the worker when available; otherwise inferred from text. */
export type JobErrorCode =
  | "auth_failed"
  | "cli_exit"
  | "cli_missing"
  | "timeout"
  | "cancelled"
  | "sync_failed"
  | "worker_error"
  | "project_missing"
  | "artifact_validation"
  | "unknown";

type Stage = "extraction" | "quote" | "proposal" | "intake";

export type JobErrorAction = {
  label: string;
  href?: string;
};

export type TranslatedJobError = {
  code: JobErrorCode;
  title: string;
  message: string;
  actions: JobErrorAction[];
  technical: string | null;
};

export function isAdminRole(role: string): boolean {
  return role === "admin";
}

export function classifyJobError(
  error: string | null,
  errorCode?: string | null,
): JobErrorCode {
  if (errorCode && isJobErrorCode(errorCode)) return errorCode;
  if (!error) return "unknown";

  const lower = error.toLowerCase();
  if (
    lower.includes("could not authenticate") ||
    lower.includes("oauth session expired") ||
    lower.includes("invalid api key")
  ) {
    return "auth_failed";
  }
  if (lower.includes("cli not found") || lower.includes("claude_bin")) return "cli_missing";
  if (lower.includes("timed out")) return "timeout";
  if (lower.includes("cancelled by estimator")) return "cancelled";
  if (lower.startsWith("claude exited") || /\bexited \d+\b/.test(lower)) return "cli_exit";
  if (lower.includes("result sync failed")) return "sync_failed";
  if (lower.includes("worker error")) return "worker_error";
  if (lower.includes("project no longer exists")) return "project_missing";
  if (lower.includes("artifact validation failed")) return "artifact_validation";
  return "unknown";
}

function isJobErrorCode(value: string): value is JobErrorCode {
  return [
    "auth_failed",
    "cli_exit",
    "cli_missing",
    "timeout",
    "cancelled",
    "sync_failed",
    "worker_error",
    "project_missing",
    "artifact_validation",
    "unknown",
  ].includes(value);
}

/** The bid stage a job belongs to, so its failure is worded for what it was doing. */
export function stageForJobType(type: string): Stage {
  if (type === "match_and_price") return "quote";
  if (type === "build_proposal") return "proposal";
  return "extraction";
}

const COPY: Record<
  JobErrorCode,
  { title: string; message: string; adminHint?: string }
> = {
  auth_failed: {
    title: "Automatic read couldn't start",
    message:
      "The system couldn't connect to run the automatic read. Your administrator needs to configure the AI provider.",
    adminHint: "Configure the provider on Settings, or sign in with the CLI, then re-run.",
  },
  cli_exit: {
    title: "Automatic read didn't finish",
    message:
      "Something went wrong while reading your documents. You can add lines by hand or try running the read again.",
  },
  cli_missing: {
    title: "Automatic read isn't available",
    message:
      "The reading service isn't set up on this installation. Contact your administrator.",
    adminHint: "Install the Claude Code CLI or set CLAUDE_BIN to its full path.",
  },
  timeout: {
    title: "Automatic read took too long",
    message:
      "The read timed out before it finished. Try again with a smaller document set, or add lines by hand.",
  },
  cancelled: {
    title: "Run cancelled",
    message: "This run was stopped. You can start a new one when you're ready.",
  },
  sync_failed: {
    title: "Results couldn't be saved",
    message:
      "The read finished but the results couldn't be saved. Try again, or add lines by hand while your administrator investigates.",
  },
  worker_error: {
    title: "Something went wrong",
    message:
      "An unexpected error stopped this run. Try again, or add lines by hand and notify your administrator if it keeps happening.",
  },
  project_missing: {
    title: "Bid no longer found",
    message: "This bid was removed while the run was in progress.",
  },
  artifact_validation: {
    title: "Automatic read finished, but its output failed the checks",
    message:
      "Nothing from this run was accepted. You can add lines by hand or try running the read again.",
  },
  unknown: {
    title: "Automatic read didn't finish",
    message:
      "Something went wrong. You can add lines by hand or try running the read again.",
  },
};

// The copy above is worded for a read. A pricing or proposal run that fails the
// same way must not tell the estimator to "try running the read again".
const STAGE_COPY: Partial<
  Record<Stage, Partial<Record<JobErrorCode, { title: string; message: string }>>>
> = {
  quote: {
    cli_exit: {
      title: "Pricing didn't finish",
      message: "Something went wrong while pricing the lines. Try running pricing again.",
    },
    timeout: {
      title: "Pricing took too long",
      message: "Pricing timed out before it finished. Try running it again.",
    },
    artifact_validation: {
      title: "Pricing finished, but its output failed the checks",
      message: "Nothing from this run was accepted. Try running pricing again.",
    },
    unknown: {
      title: "Pricing didn't finish",
      message: "Something went wrong. Try running pricing again.",
    },
  },
  proposal: {
    cli_exit: {
      title: "The proposal wasn't built",
      message: "Something went wrong while building the proposal. Try building it again.",
    },
    timeout: {
      title: "The proposal build took too long",
      message: "It timed out before it finished. Try building the proposal again.",
    },
    artifact_validation: {
      title: "The proposal was built, but it failed the checks",
      message: "Nothing from this run was accepted. Try building the proposal again.",
    },
    unknown: {
      title: "The proposal wasn't built",
      message: "Something went wrong. Try building the proposal again.",
    },
  },
};

export function jobTypeLabel(type: string): string {
  const labels: Record<string, string> = {
    extract_bid_set: "Read bid set",
    rerun_extraction: "Re-read bid set",
    match_and_price: "Price lines",
    build_proposal: "Build proposal",
    ingest_addendum: "Read addendum",
    ingest_pricebook: "Read price book",
    index_catalog: "Index catalog",
    delete_catalog: "Remove catalog index",
    run_full_pipeline: "Autopilot",
    parse_document: "Parse document",
  };
  return labels[type] ?? type.replace(/_/g, " ");
}

export function translateJobError(
  error: string | null,
  role: string,
  options?: { errorCode?: string | null; stage?: Stage },
): TranslatedJobError | null {
  if (!error) return null;

  const code = classifyJobError(error, options?.errorCode);
  const stage = options?.stage ?? "extraction";
  const copy: { title: string; message: string; adminHint?: string } =
    STAGE_COPY[stage]?.[code] ?? COPY[code];
  const admin = isAdminRole(role);

  const actions: JobErrorAction[] = [];

  if (stage === "extraction") {
    actions.push({ label: "Add lines by hand", href: "#add-by-hand" });
    actions.push({ label: "Re-run extraction" });
  } else if (stage === "quote") {
    actions.push({ label: "Re-run pricing" });
  } else if (stage === "proposal") {
    actions.push({ label: "Re-build proposal" });
  }

  if (code === "auth_failed" || code === "cli_missing") {
    if (admin) {
      actions.push({ label: "Open settings", href: "/settings" });
    } else {
      actions.push({ label: "Notify your admin" });
    }
  }

  let message = copy.message;
  if (admin && copy.adminHint) {
    message = `${copy.message} ${copy.adminHint}`;
  }

  return {
    code,
    title: copy.title,
    message,
    actions,
    technical: error,
  };
}

export function recordingUnavailableMessage(reason: string | null): string {
  if (!reason) {
    return "Detailed logs aren't available for this run. Contact support if you need help diagnosing it.";
  }
  if (reason.toLowerCase().includes("before terminal recording existed")) {
    return "Detailed logs aren't available for this run. Contact support if you need help diagnosing it.";
  }
  return reason;
}
