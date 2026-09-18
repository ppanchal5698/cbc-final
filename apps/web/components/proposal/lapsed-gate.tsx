"use client";

import { useState } from "react";
import Link from "next/link";
import { Books, ShieldWarning } from "@phosphor-icons/react";
import { toast } from "sonner";

import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { ProposalResponse } from "@/lib/types";

/**
 * The hand-off gate for lapsed price books.
 *
 * data-stewardship.md: a sheet past its review window means the margin on the
 * lines priced from it is not real. This is the only thing on the proposal
 * screen that blocks - flagged and unpriced lines are shown and left to the
 * estimator - so it offers both ways out: purchasing confirms the cost, or a
 * named person overrides and that name is recorded.
 */
export function LapsedGate({
  code,
  readiness,
  onAcknowledged,
}: {
  code: string;
  readiness: ProposalResponse["readiness"];
  onAcknowledged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  if (!readiness.lapsedLines) return null;

  if (readiness.lapsedAcknowledgedBy) {
    return (
      <div className="rounded-xl border border-subtle bg-panel px-5 py-3.5 shadow-1">
        <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          Lapsed price book
        </span>
        <p className="mt-1.5 text-[12.5px] font-medium leading-relaxed text-tx-secondary">
          {readiness.lapsedLines} line{readiness.lapsedLines === 1 ? "" : "s"} priced off a sheet
          past its review window. Overridden by {readiness.lapsedAcknowledgedBy}.
        </p>
      </div>
    );
  }

  async function acknowledge() {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${encodeURIComponent(code)}/proposal`, {
        method: "PATCH",
        body: { acknowledgeLapsed: true },
      });
      toast.success("Override recorded", { description: "Your name is on the audit trail" });
      onAcknowledged();
    } catch (problem) {
      toast.error("Could not record the override", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role="alert"
      className="rounded-xl border border-status-error/40 bg-status-error-soft px-5 py-4 shadow-1"
    >
      <div className="flex items-start gap-2.5">
        <ShieldWarning size={18} weight="duotone" className="mt-0.5 shrink-0 text-status-error" />
        <div className="min-w-0">
          <span className="block text-[13px] font-bold text-status-error">
            {readiness.lapsedLines === 1
              ? "1 line is priced from a lapsed book"
              : `${readiness.lapsedLines} lines are priced from lapsed books`}
          </span>
          <p className="mt-1 text-[12.5px] font-medium leading-relaxed text-tx-secondary">
            Purchasing has to confirm the cost before this leaves the building, or the margin on
            those lines is not real.
          </p>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Link
          href="/price-books"
          className="flex items-center gap-1.5 rounded-lg border border-subtle bg-panel px-3 py-1.5 text-[12px] font-bold text-tx-secondary no-underline shadow-1 transition-colors hover:text-tx-primary"
        >
          <Books size={14} weight="duotone" />
          Open price books
        </Link>
        <button
          type="button"
          onClick={acknowledge}
          disabled={busy}
          className="rounded-lg border border-status-error/40 bg-background px-3 py-1.5 text-[12px] font-bold text-status-error shadow-1 transition-colors hover:bg-status-error/10 disabled:opacity-50"
        >
          {busy ? "Recording…" : "Override with sign-off"}
        </button>
      </div>
    </div>
  );
}
