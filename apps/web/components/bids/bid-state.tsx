"use client";

import { toast } from "sonner";

import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { BidStatus, Outcome, Project } from "@/lib/types";

/**
 * The two chips an estimator clicks to record what happened to a bid, and the
 * one call behind them.
 *
 * Bid status and outcome are set by hand and only by hand - nothing derives
 * them from P21 or from the proposal. The API owns the two rules (marking a
 * job Not bid clears its outcome; recording an outcome means it was bid), so
 * nothing here reimplements them: this sends the change and re-reads.
 */

export const BID_STATUS_LABEL: Record<BidStatus, string> = {
  bid: "Bid",
  not_bid: "Not bid",
};

export const OUTCOME_LABEL: Record<Outcome, string> = {
  "": "Open",
  won: "Won",
  lost: "Lost",
};

/** One click cycles open -> won -> lost -> open, as the prototype does. */
export function nextOutcome(current: Outcome | undefined): Outcome {
  return current === "" || current === undefined ? "won" : current === "won" ? "lost" : "";
}

export function bidStatusTone(status: BidStatus): string {
  return status === "not_bid"
    ? "border-subtle bg-panel-muted text-tx-secondary"
    : "border-brand-border bg-brand-soft text-brand-primary";
}

export function outcomeTone(outcome: Outcome): string {
  if (outcome === "won")
    return "border-status-success-border bg-status-success-soft text-status-success";
  if (outcome === "lost")
    return "border-status-error-border bg-status-error-soft text-status-error";
  return "border-subtle bg-transparent text-tx-muted";
}

export async function patchBid(
  project: Project,
  body: Record<string, unknown>,
  onDone: () => void,
): Promise<void> {
  try {
    await proxyMutate(`/api/proxy/projects/${encodeURIComponent(project.code)}`, {
      method: "PATCH",
      body,
    });
    onDone();
  } catch (problem) {
    toast.error(`Could not update ${project.code}`, { description: errorMessage(problem) });
  }
}
