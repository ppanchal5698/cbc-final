"use client";

import { useState } from "react";
import useSWR from "swr";
import { Eye, PencilLine, WarningDiamond, X } from "@phosphor-icons/react/dist/ssr";

import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { ReviewFlag } from "@/lib/types";

/**
 * Fields the API uses for "there is something here the pass could not read".
 *
 * `accuracy-trust` rule 4: unparsed content is reported explicitly - silence is
 * not an acceptable way to say "I could not read this". These already come back
 * from GET /api/projects/{code}/review-flags, derived on every read; this panel
 * only puts them where the estimator is looking when it still matters, instead
 * of on the proposal at the end.
 */
const UNREAD_FIELDS = new Set(["document_not_parsed", "ocr_unavailable", "no_scope"]);

const WHAT: Record<string, string> = {
  document_not_parsed: "A document was not fully read",
  ocr_unavailable: "A scanned page could not be OCR'd",
  no_scope: "No Division 08 openings were found",
};

export function UnreadPanel({
  code,
  onShowSheet,
  onAddByHand,
}: {
  code: string;
  onShowSheet: (page: number) => void;
  onAddByHand: () => void;
}) {
  const [dismissed, setDismissed] = useState(false);
  const { data } = useSWR<{ flags: ReviewFlag[] }>(
    `/api/proxy/projects/${encodeURIComponent(code)}/review-flags`,
    proxyFetcher,
  );

  const unread = (data?.flags ?? []).filter((flag) => UNREAD_FIELDS.has(flag.field ?? ""));
  if (dismissed || unread.length === 0) return null;

  return (
    <section
      aria-labelledby="unread-title"
      className="anim-fadein rounded-xl border border-status-warning/30 bg-status-warning-soft"
    >
      <div className="flex items-start gap-3 px-5 py-3.5">
        <WarningDiamond size={18} weight="duotone" className="mt-0.5 shrink-0 text-status-warning" />
        <div className="min-w-0 flex-1">
          <h2 id="unread-title" className="text-[13.5px] font-bold text-status-warning">
            {unread.length === 1
              ? "1 thing on the plans was not read"
              : `${unread.length} things on the plans were not read`}
          </h2>
          <p className="mt-0.5 text-[12px] font-medium leading-relaxed text-tx-secondary">
            The pass flags what it could not resolve so nothing quietly falls off the quote.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss the unread-content notice"
          className="shrink-0 rounded-md p-1 text-tx-muted transition-colors hover:bg-panel-muted hover:text-tx-primary"
        >
          <X size={14} weight="bold" />
        </button>
      </div>

      <ul className="flex flex-col border-t border-status-warning/20">
        {unread.map((flag, index) => (
          <li
            key={`${flag.field}-${flag.source_page ?? index}`}
            className="flex flex-wrap items-center gap-3 border-b border-status-warning/10 px-5 py-2.5 last:border-b-0"
          >
            <span className="flex min-w-0 flex-1 flex-col leading-tight">
              <span className="text-[12.5px] font-semibold text-tx-primary">
                {WHAT[flag.field ?? ""] ?? "Unresolved content"}
                {flag.source_page ? ` · page ${flag.source_page}` : ""}
              </span>
              <span className="text-[11.5px] font-medium leading-relaxed text-tx-secondary">
                {flag.note ?? flag.issue ?? flag.action_required}
              </span>
            </span>

            {flag.source_page ? (
              <button
                type="button"
                onClick={() => onShowSheet(flag.source_page as number)}
                className="flex shrink-0 items-center gap-1.5 rounded-lg border border-subtle bg-panel px-2.5 py-1.5 text-[12px] font-semibold text-tx-secondary transition-colors hover:text-tx-primary"
              >
                <Eye size={14} weight="duotone" />
                See it on the sheet
              </button>
            ) : null}

            <button
              type="button"
              onClick={onAddByHand}
              className="flex shrink-0 items-center gap-1.5 rounded-lg border border-status-error/30 bg-status-error-soft px-2.5 py-1.5 text-[12px] font-semibold text-status-error transition-colors hover:brightness-125"
            >
              <PencilLine size={14} weight="duotone" />
              Add it by hand
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
