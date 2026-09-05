"use client";

import { useUiState } from "@/components/shell/ui-state";
import { cn } from "@/lib/utils";

/**
 * The rail's bottom card.
 *
 * Focus mode quiets the run pill and the notification badge so a long review
 * pass is not interrupted by a job finishing. It hides nothing that would let a
 * flagged line slip through - the counts on the extraction screen stay put.
 */
export function FocusCard({ user }: { user: { name: string; initials: string } }) {
  const { focusMode, toggleFocus } = useUiState();

  return (
    <div className="m-3 rounded-xl border border-subtle bg-panel p-4 shadow-sm transition-colors hover:border-brand-border">
      <div className="flex items-center gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-brand-soft text-[11.5px] font-semibold text-brand-primary shadow-sm">
          {user.initials}
        </span>
        <span className="truncate text-[13px] font-semibold text-tx-primary">{user.name}</span>
      </div>

      <div className="mt-4 flex items-center justify-between">
        <span className="text-[12px] font-medium text-tx-secondary">Focus mode</span>
        <button
          onClick={toggleFocus}
          role="switch"
          aria-checked={focusMode}
          aria-label="Focus mode"
          className={cn(
            "relative h-5 w-9 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border",
            focusMode ? "bg-brand-primary" : "bg-panel-muted border border-subtle"
          )}
        >
          <span
            className={cn(
              "absolute top-0.5 h-4 w-4 rounded-full bg-white transition-all shadow-sm",
              focusMode ? "left-[18px]" : "left-0.5"
            )}
          />
        </button>
      </div>

      <p className="mt-3 text-[11px] leading-relaxed text-tx-muted font-medium">
        {focusMode
          ? "Run status and the review queue badge are quiet."
          : "Quiets run status and the review queue badge."}
      </p>
    </div>
  );
}
