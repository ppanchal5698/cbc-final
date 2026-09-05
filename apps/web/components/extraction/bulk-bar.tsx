"use client";

import { useState } from "react";
import { Checks, Trash, ArrowsLeftRight } from "@phosphor-icons/react/dist/ssr";

export function BulkBar({
  selected,
  total,
  busy,
  alternates,
  onSelectAll,
  onConfirm,
  onRemove,
  onClear,
  onAssignAlternate,
}: {
  selected: number;
  total: number;
  busy: boolean;
  alternates?: { name: string | null; label: string }[];
  onSelectAll: () => void;
  onConfirm: () => void;
  onRemove: () => void;
  onClear: () => void;
  onAssignAlternate?: (alternate: string | null) => void;
}) {
  const [assignOpen, setAssignOpen] = useState(false);
  const groups = alternates ?? [];

  if (selected === 0) return null;

  return (
    <div className="anim-fadein flex items-center gap-3 border-t border-subtle bg-brand-primary/10 px-5 py-3">
      <span className="text-[13px] font-bold text-brand-primary">
        {selected} selected
      </span>
      <button
        onClick={onSelectAll}
        className="text-[12.5px] font-medium text-tx-secondary underline-offset-4 hover:text-tx-primary hover:underline transition-colors"
      >
        Select all {total}
      </button>

      <span className="flex-1" />

      {onAssignAlternate && groups.length > 0 && (
        <div className="relative">
          <button
            onClick={() => setAssignOpen((open) => !open)}
            disabled={busy}
            className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors disabled:opacity-50 shadow-sm bg-background"
          >
            <ArrowsLeftRight size={14} weight="bold" />
            Move to group
          </button>
          {assignOpen && (
            <div className="absolute bottom-full right-0 z-20 mb-2 min-w-[180px] rounded-xl py-1.5 shadow-xl bg-panel border border-subtle">
              {groups.map((group) => (
                <button
                  key={group.label}
                  onClick={() => {
                    onAssignAlternate(group.name);
                    setAssignOpen(false);
                  }}
                  className="block w-full px-4 py-2 text-left text-[12.5px] font-medium text-tx-primary hover:bg-background/50 transition-colors"
                >
                  {group.label}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      <button
        onClick={onConfirm}
        disabled={busy}
        aria-label={`Confirm ${selected} selected lines`}
        className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold disabled:opacity-50 transition-colors bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
      >
        <Checks size={16} weight="bold" />
        Confirm {selected}
      </button>
      <button
        onClick={onRemove}
        disabled={busy}
        aria-label={`Remove ${selected} selected lines`}
        className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold disabled:opacity-50 transition-colors border border-status-error/30 text-status-error bg-status-error-soft hover:bg-status-error/10 shadow-sm"
      >
        <Trash size={16} weight="fill" />
        Remove
      </button>
      <button
        onClick={onClear}
        className="rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-background"
      >
        Clear
      </button>
    </div>
  );
}
