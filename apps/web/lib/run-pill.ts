import type { ChainState, Job } from "@/lib/types";
import { jobTypeLabel } from "@/lib/job-error";

export type RunPill = { label: string; tone: "running" | "done" | "failed" } | null;

const BLOCKED_CHAIN: ReadonlySet<ChainState> = new Set([
  "extraction_needs_review",
  "pricing_failed",
  "quoting_failed",
  "awaiting_manual_retry",
  "dead",
]);

/** A queued extract still inside its quiet window, waiting for sibling PDFs. */
export function waitingForSiblings(job: Job): boolean {
  if (job.status !== "queued" || !job.nextAttemptAt) return false;
  return new Date(job.nextAttemptAt).getTime() > Date.now();
}

function runningLabel(job: Job, phase?: string | null): string {
  if (job.type === "run_full_pipeline") {
    return phase ? `Autopilot · ${phase}…` : "Autopilot · starting…";
  }
  if (job.stragglerPending && job.status === "running") {
    return "Reading… (late PDF will re-run)";
  }
  const byType: Record<string, string> = {
    extract_bid_set: "Reading the bid set…",
    rerun_extraction: "Re-reading the bid set…",
    match_and_price: "Pricing lines…",
    build_proposal: "Building proposal…",
    ingest_addendum: "Reading addendum…",
    parse_document: "Parsing with MinerU…",
  };
  return byType[job.type] ?? `${jobTypeLabel(job.type)}…`;
}

/**
 * The status pill in the header.
 *
 * Lives outside the client component so server pages can call it - a plain
 * function exported from a "use client" module is not callable on the server.
 */
export function runPillFor(
  job: Job | null | undefined,
  itemCount?: number,
  phase?: string | null,
  chainState?: ChainState | null,
): RunPill {
  if (job?.status === "running") {
    return { label: runningLabel(job, phase), tone: "running" };
  }
  if (job?.status === "queued") {
    if (waitingForSiblings(job)) {
      return { label: "Waiting for more files…", tone: "running" };
    }
    return { label: "Queued…", tone: "running" };
  }
  if (job?.status === "failed" || job?.status === "dead") {
    return { label: "Needs attention", tone: "failed" };
  }
  if (chainState && BLOCKED_CHAIN.has(chainState)) {
    return { label: "Needs attention", tone: "failed" };
  }
  if (!job) {
    return itemCount ? { label: `Pass complete · ${itemCount} items`, tone: "done" } : null;
  }
  return { label: `Pass complete · ${itemCount ?? 0} items`, tone: "done" };
}
