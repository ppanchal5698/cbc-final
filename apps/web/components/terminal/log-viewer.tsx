"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  countByFilter,
  entryMatchesFilter,
  type LogEntry,
  type LogFilter,
} from "@/lib/claude-stream";
import type { RecordingState } from "@/hooks/use-job-recording";

import { LogEntryRow } from "./log-entry-row";

const FILTERS: { id: LogFilter; label: string }[] = [
  { id: "all", label: "All" },
  { id: "agent", label: "Agent" },
  { id: "tools", label: "Tools" },
  { id: "system", label: "System" },
  { id: "errors", label: "Errors" },
];

export function LogViewer({
  entries,
  state,
}: {
  entries: LogEntry[];
  state: RecordingState;
}) {
  const [filter, setFilter] = useState<LogFilter>("all");
  const [pinnedBottom, setPinnedBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const counts = useMemo(() => countByFilter(entries), [entries]);
  const visible = useMemo(
    () => entries.filter((entry) => entryMatchesFilter(entry, filter)),
    [entries, filter],
  );

  const isNearBottom = () => {
    const el = scrollRef.current;
    if (!el) return true;
    return el.scrollTop + el.clientHeight >= el.scrollHeight - 48;
  };

  useEffect(() => {
    if (!pinnedBottom) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [visible.length, pinnedBottom, state]);

  const onScroll = () => {
    setPinnedBottom(isNearBottom());
  };

  const jumpToBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setPinnedBottom(true);
  };

  return (
    <div className="terminal-log flex h-full min-h-0 flex-col bg-background">
      <div className="flex flex-wrap items-center gap-2 px-4 py-2 border-b border-subtle bg-panel-muted/30">
        {FILTERS.map((chip) => {
          const on = filter === chip.id;
          const count = counts[chip.id];
          return (
            <button
              key={chip.id}
              type="button"
              onClick={() => setFilter(chip.id)}
              className={`rounded-lg px-3 py-1 text-[11px] font-bold transition-colors shadow-sm ${
                on
                  ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                  : "border border-subtle text-tx-muted hover:bg-panel-muted hover:text-tx-primary"
              }`}
            >
              {chip.label}
              {chip.id !== "all" && count > 0 ? ` (${count})` : ""}
            </button>
          );
        })}
        <span className="flex-1" />
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          {visible.length} events
        </span>
      </div>

      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={onScroll}
          className="terminal-log-scroll h-full overflow-y-auto py-2"
        >
          {visible.length === 0 ? (
            <div className="px-4 py-8 text-center text-[13px] font-medium text-tx-muted">
              {state === "connecting"
                ? "Connecting to run recording…"
                : "No events match this filter yet."}
            </div>
          ) : (
            visible.map((entry) => <LogEntryRow key={entry.id} entry={entry} />)
          )}
        </div>

        {!pinnedBottom && state === "live" ? (
          <button
            type="button"
            onClick={jumpToBottom}
            className="absolute bottom-4 left-1/2 -translate-x-1/2 rounded-full px-4 py-1.5 text-[12px] font-bold shadow-lg bg-panel border border-brand-primary/30 text-brand-primary hover:bg-brand-primary/10 transition-colors"
          >
            ↓ New output
          </button>
        ) : null}
      </div>
    </div>
  );
}
