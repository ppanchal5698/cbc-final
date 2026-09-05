"use client";

import { useState } from "react";
import { CaretDown, CaretRight, Warning } from "@phosphor-icons/react/dist/ssr";

import { AgentText } from "@/lib/format-agent-text";
import type { LogEntry } from "@/lib/claude-stream";

const PREVIEW_LIMIT = 2048;

function truncate(text: string, limit = PREVIEW_LIMIT): { text: string; truncated: boolean } {
  if (text.length <= limit) return { text, truncated: false };
  return { text: text.slice(0, limit), truncated: true };
}

function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: "ok" | "failed" | "neutral";
}) {
  const colorClass =
    tone === "ok"
      ? "bg-status-success-soft text-status-success border-status-success/30"
      : tone === "failed"
        ? "bg-status-error-soft text-status-error border-status-error/30"
        : "bg-panel-muted text-tx-muted border-subtle";

  return (
    <span className={`rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest border shadow-sm ${colorClass}`}>
      {label}
    </span>
  );
}

function ToolCallRow({ entry }: { entry: Extract<LogEntry, { kind: "tool_call" }> }) {
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const result = entry.result;
  const resultPreview = result ? truncate(result.body) : null;

  return (
    <div className="tool-card rounded-xl border border-subtle bg-panel shadow-sm overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left text-tx-primary hover:bg-background/50 transition-colors"
      >
        {open ? <CaretDown size={14} weight="bold" /> : <CaretRight size={14} weight="bold" />}
        <span className="text-[11px] font-bold uppercase tracking-widest text-brand-primary">
          call
        </span>
        <span className="font-mono text-[12.5px] font-medium">{entry.name}</span>
        {entry.summary ? (
          <span className="truncate font-mono text-[11.5px] text-tx-muted">
            {entry.summary}
          </span>
        ) : null}
        <span className="flex-1" />
        {result ? (
          <>
            <StatusBadge label={result.isError ? "failed" : "ok"} tone={result.isError ? "failed" : "ok"} />
            <span className="font-mono text-[11px] font-medium text-tx-muted">
              {result.size.toLocaleString()} chars
            </span>
          </>
        ) : (
          <StatusBadge label="pending" tone="neutral" />
        )}
      </button>

      {open ? (
        <div className="space-y-3 px-4 pb-4 pt-2 border-t border-subtle bg-background">
          <div>
            <div className="mb-1.5 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              Input
            </div>
            <pre className="terminal-code-block">{formatJson(entry.input)}</pre>
          </div>
          {result ? (
            <div>
              <div className="mb-1.5 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Result
              </div>
              <pre className="terminal-code-block">
                {showAll || !resultPreview?.truncated
                  ? result.body
                  : resultPreview.text}
              </pre>
              {resultPreview?.truncated ? (
                <button
                  type="button"
                  onClick={() => setShowAll((v) => !v)}
                  className="mt-2 text-[12px] font-bold text-brand-primary hover:text-brand-primary/80 transition-colors"
                >
                  {showAll ? "Show less" : "Show all"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

export function LogEntryRow({ entry }: { entry: LogEntry }) {
  return (
    <div className="terminal-log-row grid grid-cols-[64px_1fr] md:grid-cols-[80px_1fr] gap-3 px-4 py-2 hover:bg-background/50 transition-colors">
      <time className="tnum pt-1 font-mono text-[11px] font-medium text-tx-muted text-right">
        {entry.time}
      </time>

      <div className="min-w-0 flex flex-col gap-2">
        {entry.kind === "session" ? (
          <div className="rounded-xl px-4 py-3 bg-panel border border-subtle shadow-sm">
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-[11px] font-bold uppercase tracking-widest text-brand-primary">
                session
              </span>
              <span className="rounded-md px-2 py-0.5 font-mono text-[12px] font-medium bg-brand-primary/10 text-brand-primary border border-brand-primary/20">
                {entry.model}
              </span>
              <span className="text-[12px] font-medium text-tx-muted">
                {entry.toolCount} tools
              </span>
            </div>
            {entry.mcpServers.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-2">
                {entry.mcpServers.map((server) => (
                  <span
                    key={`${server.name}-${server.status}`}
                    className={`rounded-md px-2 py-0.5 font-mono text-[11px] font-medium border shadow-sm ${
                      server.status === "connected"
                        ? "bg-status-success-soft text-status-success border-status-success/30"
                        : "bg-panel-muted text-tx-muted border-subtle"
                    }`}
                  >
                    {server.name}:{server.status}
                  </span>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {entry.kind === "warning" || entry.kind === "api_retry" ? (
          <div className="flex items-start gap-3 rounded-xl px-4 py-3 bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm">
            <Warning size={16} weight="fill" className="mt-0.5 shrink-0" />
            <div className="min-w-0 text-[13px] font-medium leading-relaxed">
              {entry.kind === "api_retry"
                ? `API retry ${entry.attempt}/${entry.maxRetries}: ${entry.error}`
                : entry.message}
            </div>
          </div>
        ) : null}

        {entry.kind === "agent_text" ? (
          <div className="rounded-xl px-4 py-3 bg-panel border border-subtle shadow-sm">
            <AgentText text={entry.text} />
          </div>
        ) : null}

        {entry.kind === "tool_call" ? <ToolCallRow entry={entry} /> : null}

        {entry.kind === "error" ? (
          <div className="rounded-xl border-l-4 border-status-error px-4 py-3 text-[13px] font-medium bg-status-error-soft text-status-error shadow-sm">
            {entry.message}
          </div>
        ) : null}

        {entry.kind === "done" ? (
          <div
            className={`flex flex-wrap items-center gap-3 rounded-xl px-4 py-3 text-[13px] font-bold shadow-sm border ${
              entry.isError
                ? "bg-status-error-soft text-status-error border-status-error/30"
                : "bg-status-success-soft text-status-success border-status-success/30"
            }`}
          >
            <span className="uppercase tracking-widest text-[11px]">done</span>
            <span>
              {entry.turns} turns in {entry.seconds}s
            </span>
            {entry.costUsd != null ? <span>${entry.costUsd.toFixed(3)}</span> : null}
          </div>
        ) : null}

        {entry.kind === "rate_limit" ? (
          <div className="text-[13px] font-bold text-status-warning">
            rate limit: {entry.subtype}
          </div>
        ) : null}

        {entry.kind === "plain" ? (
          <div className="font-mono text-[12px] font-medium text-tx-muted">
            {entry.text}
          </div>
        ) : null}
      </div>
    </div>
  );
}
