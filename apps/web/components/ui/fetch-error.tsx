"use client";

import { errorMessage } from "@/lib/proxy-fetcher";

/** Inline retry banner for SWR fetch failures. */
export function FetchError({
  title,
  error,
  onRetry,
  compact = false,
}: {
  title: string;
  error: unknown;
  onRetry: () => void;
  compact?: boolean;
}) {
  if (compact) {
    return (
      <p className="px-5 py-4 text-[13px] font-medium text-status-error bg-status-error-soft rounded-lg border border-status-error/30 shadow-sm">
        {title}: {errorMessage(error)}{" "}
        <button
          type="button"
          onClick={onRetry}
          className="underline hover:text-tx-primary transition-colors ml-1 font-semibold"
        >
          Retry
        </button>
      </p>
    );
  }

  return (
    <div className="grid place-items-center gap-3 px-6 py-12 text-center rounded-xl bg-panel-muted border border-subtle shadow-sm">
      <div className="grid gap-1">
        <span className="text-[15px] font-bold text-status-error tracking-tight">
          {title}
        </span>
        <span className="max-w-[420px] text-[13px] font-medium text-tx-secondary">
          {errorMessage(error)}
        </span>
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 rounded-md px-4 py-2 text-[13px] font-semibold border border-subtle bg-background text-tx-primary hover:bg-panel-muted transition-colors shadow-sm"
      >
        Try again
      </button>
    </div>
  );
}
