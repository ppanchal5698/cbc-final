"use client";

import { useCallback, useEffect, useRef } from "react";
import type { Terminal } from "@xterm/xterm";
import { Copy } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { useJobRecording, type RecordingState } from "@/hooks/use-job-recording";
import { formatEntriesForCopy } from "@/lib/claude-stream";
import { recordingUnavailableMessage } from "@/lib/job-error";

import { LogViewer } from "./log-viewer";

import "@xterm/xterm/css/xterm.css";

/**
 * The real Claude Code session — structured log viewer by default, xterm for raw.
 *
 * The worker runs the CLI and records every byte; this replays the stream-json
 * events as they happen. Structured mode renders agent text, tool calls, and
 * errors as readable UI; raw mode shows the untouched JSON lines in xterm.
 *
 * It is read-only. There is no path from this component back into the process.
 */
export function RunTerminal({
  jobId,
  status,
  onFinished,
  raw = false,
}: {
  jobId: string;
  status?: string;
  onFinished?: (status: string) => void;
  /** Show the CLI's event stream unfiltered, exactly as it arrived. */
  raw?: boolean;
}) {
  const rawWriter = useRef<((lines: string) => void) | null>(null);
  const rawBuffer = useRef("");
  const onRawChunk = useCallback((lines: string) => {
    if (rawWriter.current) {
      rawWriter.current(lines);
    } else {
      rawBuffer.current += lines;
    }
  }, []);

  const { entries, state, reason, getRawLog } = useJobRecording(jobId, {
    onFinished,
    onRawChunk: raw ? onRawChunk : undefined,
    parseEntries: !raw,
  });

  const copyLogs = useCallback(async () => {
    const text = raw ? getRawLog() : formatEntriesForCopy(entries);
    if (!text.trim()) {
      toast.error("Nothing to copy yet", {
        description: state === "connecting" ? "Waiting for run output…" : "This run has no log events.",
      });
      return;
    }
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Log copied to clipboard");
    } catch {
      toast.error("Clipboard blocked", {
        description: "Select the text in the log view instead.",
      });
    }
  }, [raw, getRawLog, entries, state]);

  return (
    <div className="flex h-full flex-col">
      <StatusStrip
        state={state}
        status={status}
        reason={reason}
        raw={raw}
        onCopy={copyLogs}
        copyDisabled={state === "unavailable"}
      />
      <div className="min-h-0 flex-1 bg-background">
        {raw ? (
          state === "unavailable" ? (
            <div className="px-4 py-6 text-[13px] font-medium text-tx-muted text-center">
              {recordingUnavailableMessage(reason)}
            </div>
          ) : (
            <RawXtermViewer
              registerWriter={(writer) => {
                rawWriter.current = writer;
                if (rawBuffer.current) {
                  writer(rawBuffer.current);
                  rawBuffer.current = "";
                }
              }}
            />
          )
        ) : state === "unavailable" ? (
          <div className="px-4 py-6 text-[13px] font-medium text-tx-muted text-center">
            {recordingUnavailableMessage(reason)}
          </div>
        ) : (
          <LogViewer entries={entries} state={state} />
        )}
      </div>
    </div>
  );
}

function StatusStrip({
  state,
  status,
  reason,
  raw,
  onCopy,
  copyDisabled,
}: {
  state: RecordingState;
  status?: string;
  reason: string | null;
  raw: boolean;
  onCopy: () => void;
  copyDisabled: boolean;
}) {
  return (
    <div className="flex items-center gap-2 px-4 py-2 text-[11px] font-bold uppercase tracking-widest border-b border-subtle text-tx-muted bg-panel-muted/50">
      <span
        className="h-2 w-2 rounded-full shadow-sm"
        style={{
          background:
            state === "live"
              ? "var(--color-brand-primary)"
              : state === "ended"
                ? "var(--color-tx-muted)"
                : "var(--color-status-warning)",
        }}
      />
      <span>
        {raw
          ? state === "live"
            ? "claude · raw json · live"
            : state === "ended"
              ? `claude · raw · ${status ?? "finished"}`
              : state === "unavailable"
                ? (reason ?? "no recording")
                : "connecting…"
          : state === "live"
            ? "claude · structured · live"
            : state === "ended"
              ? `claude · ${status ?? "finished"}`
              : state === "unavailable"
                ? (reason ?? "no recording")
                : "connecting…"}
      </span>
      <span className="flex-1" />
      <button
        type="button"
        onClick={onCopy}
        disabled={copyDisabled}
        aria-label="Copy entire run log to clipboard"
        className="flex items-center gap-1.5 rounded-md px-2 py-1 normal-case tracking-normal font-bold text-tx-muted hover:bg-panel hover:text-tx-primary transition-colors disabled:opacity-40 disabled:pointer-events-none"
      >
        <Copy size={14} weight="bold" />
        Copy log
      </button>
      <span>read-only</span>
    </div>
  );
}

function RawXtermViewer({
  registerWriter,
}: {
  registerWriter: (writer: (lines: string) => void) => void;
}) {
  const holder = useRef<HTMLDivElement | null>(null);
  const term = useRef<Terminal | null>(null);
  const pending = useRef("");

  useEffect(() => {
    let disposed = false;
    let fit: { fit: () => void; dispose: () => void } | null = null;
    let observer: ResizeObserver | null = null;

    registerWriter((lines) => {
      if (term.current) {
        term.current.write(lines);
      } else {
        pending.current += lines;
      }
    });

    (async () => {
      const [{ Terminal: XTerm }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);
      if (disposed || !holder.current) return;

      const styles = getComputedStyle(document.documentElement);
      const token = (name: string, fallback: string) =>
        styles.getPropertyValue(name).trim() || fallback;

      const terminal = new XTerm({
        convertEol: false,
        cursorBlink: false,
        disableStdin: true,
        scrollback: 20000,
        fontSize: 12,
        fontFamily:
          "var(--font-mono, ui-monospace), SFMono-Regular, Menlo, Consolas, monospace",
        theme: {
          background: token("--color-background", "#0b0d10"),
          foreground: token("--color-tx-primary", "#d8dde5"),
          cursor: token("--color-brand-primary", "#7aa2f7"),
          selectionBackground: token("--color-brand-primary", "#24314d") + "33", // appending alpha
        },
      });
      const fitAddon = new FitAddon();
      terminal.loadAddon(fitAddon);
      terminal.open(holder.current);
      fitAddon.fit();
      term.current = terminal;
      if (pending.current) {
        terminal.write(pending.current);
        pending.current = "";
      }
      fit = fitAddon;

      observer = new ResizeObserver(() => {
        try {
          fitAddon.fit();
        } catch {
          /* the pane can be measured mid-layout; the next tick fixes it */
        }
      });
      observer.observe(holder.current);
    })();

    return () => {
      disposed = true;
      registerWriter(() => {});
      observer?.disconnect();
      fit?.dispose();
      term.current?.dispose();
      term.current = null;
    };
  }, [registerWriter]);

  return <div ref={holder} className="h-full min-h-0 px-2 py-1.5" />;
}
