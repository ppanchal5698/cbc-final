"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import useSWR from "swr";
import { X, Prohibit, CaretDown, CaretUp } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { useUiState } from "@/components/shell/ui-state";
import { useDialog } from "@/hooks/use-dialog";
import type { Job, JobStatus } from "@/lib/types";
import { FetchError } from "@/components/ui/fetch-error";
import { endpoints } from "@/lib/endpoints";
import {
  isAdminRole,
  jobTypeLabel,
  translateJobError,
} from "@/lib/job-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";

const RunTerminal = dynamic(
  () => import("@/components/terminal/run-terminal").then((m) => m.RunTerminal),
  { ssr: false },
);

const TERMINAL_HEIGHT_KEY = "opshub-terminal-height";
const DEFAULT_HEIGHT = 560;
const MIN_HEIGHT = 180;

function maxTerminalHeight(): number {
  if (typeof window === "undefined") return DEFAULT_HEIGHT;
  return Math.floor(window.innerHeight * 0.92);
}

function clampTerminalHeight(height: number): number {
  return Math.max(MIN_HEIGHT, Math.min(height, maxTerminalHeight()));
}

function readStoredTerminalHeight(): number | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(TERMINAL_HEIGHT_KEY);
    if (!raw) return null;
    const parsed = Number.parseInt(raw, 10);
    return Number.isFinite(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function rememberTerminalHeight(height: number): void {
  try {
    localStorage.setItem(TERMINAL_HEIGHT_KEY, String(height));
  } catch {
    /* private browsing */
  }
}

const TERMINAL_HEIGHT_EVENT = "opshub-terminal-height-change";

function preferredTerminalHeight(): number {
  const stored = readStoredTerminalHeight();
  if (typeof window === "undefined") return DEFAULT_HEIGHT;
  return clampTerminalHeight(
    stored ?? Math.min(Math.floor(window.innerHeight * 0.52), DEFAULT_HEIGHT),
  );
}

function subscribeTerminalHeight(onStoreChange: () => void): () => void {
  window.addEventListener("storage", onStoreChange);
  window.addEventListener(TERMINAL_HEIGHT_EVENT, onStoreChange);
  window.addEventListener("resize", onStoreChange);
  return () => {
    window.removeEventListener("storage", onStoreChange);
    window.removeEventListener(TERMINAL_HEIGHT_EVENT, onStoreChange);
    window.removeEventListener("resize", onStoreChange);
  };
}

function useTerminalDrawerHeight(): {
  height: number;
  startResize: (clientY: number) => void;
  nudgeHeight: (delta: number) => void;
} {
  const preferred = useSyncExternalStore(
    subscribeTerminalHeight,
    preferredTerminalHeight,
    () => DEFAULT_HEIGHT,
  );
  // Drag/nudge overrides the preferred height until the next persist.
  const [override, setOverride] = useState<number | null>(null);
  const height = clampTerminalHeight(override ?? preferred);
  // Keep the override inside the window clamp when the viewport shrinks.
  if (override !== null && override !== height) {
    setOverride(height);
  }
  const dragRef = useRef<{ startY: number; startHeight: number } | null>(null);
  const heightRef = useRef(height);

  useEffect(() => {
    heightRef.current = height;
  }, [height]);

  useEffect(() => {
    function onPointerMove(event: PointerEvent) {
      if (!dragRef.current) return;
      const delta = dragRef.current.startY - event.clientY;
      setOverride(clampTerminalHeight(dragRef.current.startHeight + delta));
    }

    function onPointerUp() {
      if (!dragRef.current) return;
      dragRef.current = null;
      rememberTerminalHeight(heightRef.current);
      window.dispatchEvent(new Event(TERMINAL_HEIGHT_EVENT));
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }

    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
    window.addEventListener("pointercancel", onPointerUp);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerUp);
      window.removeEventListener("pointercancel", onPointerUp);
    };
  }, []);

  const startResize = useCallback((clientY: number) => {
    dragRef.current = { startY: clientY, startHeight: heightRef.current };
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
  }, []);

  const nudgeHeight = useCallback((delta: number) => {
    setOverride((current) => {
      const base = current ?? preferredTerminalHeight();
      const next = clampTerminalHeight(base + delta);
      rememberTerminalHeight(next);
      window.dispatchEvent(new Event(TERMINAL_HEIGHT_EVENT));
      return next;
    });
  }, []);

  return { height, startResize, nudgeHeight };
}

function statusColor(status: JobStatus): string {
  switch (status) {
    case "running":
      return "var(--color-brand-primary)";
    case "done":
      return "var(--color-status-success)";
    case "failed":
    case "cancelled":
      return "var(--color-status-error)";
    default:
      return "var(--color-tx-muted)";
  }
}

function statusLabel(status: JobStatus): string {
  switch (status) {
    case "running":
      return "running";
    case "done":
      return "done";
    case "failed":
      return "failed";
    case "cancelled":
      return "cancelled";
    default:
      return "queued";
  }
}

export function TerminalDrawer({ code }: { code: string | null }) {
  const { terminalOpen, setTerminalOpen, userRole } = useUiState();
  const { height, startResize, nudgeHeight } = useTerminalDrawerHeight();
  const [selected, setSelected] = useState<string | null>(null);
  const [raw, setRaw] = useState(false);
  const [showTechnicalLog, setShowTechnicalLog] = useState(isAdminRole(userRole));
  const [resetKey, setResetKey] = useState<string | null>(null);
  const openKey = terminalOpen ? `${code}:${userRole}` : null;
  if (openKey !== null && openKey !== resetKey) {
    setResetKey(openKey);
    setShowTechnicalLog(isAdminRole(userRole));
  } else if (openKey === null && resetKey !== null) {
    setResetKey(null);
  }

  const close = useCallback(() => setTerminalOpen(false), [setTerminalOpen]);
  const dialogRef = useDialog<HTMLDivElement>(terminalOpen, close);
  const [cancelling, setCancelling] = useState(false);

  const { data, error, mutate } = useSWR<{ jobs: Job[] }>(
    terminalOpen && code ? `/api/proxy/jobs?project=${encodeURIComponent(code)}&limit=12` : null,
    proxyFetcher,
    { refreshInterval: 5000 },
  );

  if (!terminalOpen || !code) return null;

  const jobs = data?.jobs ?? [];
  const active = jobs.find((j) => j.id === selected) ?? jobs[0];
  const canCancel =
    active && (active.status === "queued" || active.status === "running");
  const failureSummary =
    active?.status === "failed" || active?.status === "dead"
      ? translateJobError(active.error, userRole, { errorCode: active.errorCode })
      : null;

  async function cancelActiveJob() {
    if (!active || !canCancel) return;
    if (
      !window.confirm(
        `Cancel this ${jobTypeLabel(active.type)} run? It will stop after the current step finishes.`,
      )
    ) {
      return;
    }
    setCancelling(true);
    try {
      await proxyMutate(endpoints.jobCancel(active.id), { method: "POST" });
      toast.success("Run cancelled");
      mutate();
    } catch (problem) {
      toast.error("Could not cancel that run", { description: errorMessage(problem) });
    } finally {
      setCancelling(false);
    }
  }

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-label={`Run status for ${code}`}
      className="fixed inset-x-0 bottom-0 z-40 flex flex-col bg-background border-t border-subtle shadow-2xl"
      style={{ height }}
    >
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize run status panel"
        aria-valuenow={height}
        aria-valuemin={MIN_HEIGHT}
        aria-valuemax={maxTerminalHeight()}
        tabIndex={0}
        onPointerDown={(event) => {
          event.preventDefault();
          startResize(event.clientY);
        }}
        onKeyDown={(event) => {
          const step = event.shiftKey ? 48 : 16;
          if (event.key === "ArrowUp") {
            event.preventDefault();
            nudgeHeight(step);
          } else if (event.key === "ArrowDown") {
            event.preventDefault();
            nudgeHeight(-step);
          }
        }}
        className="group flex h-2.5 shrink-0 cursor-ns-resize touch-none items-center justify-center border-b border-subtle bg-panel-muted/40 hover:bg-panel-muted/70 active:bg-panel-muted transition-colors"
      >
        <span className="h-1 w-12 rounded-full bg-tx-muted/35 group-hover:bg-tx-muted/55 group-active:bg-tx-muted/70 transition-colors" />
      </div>

      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-subtle bg-panel-muted/50 backdrop-blur-md">
        <span className="text-[13px] font-bold text-tx-primary tracking-tight">Run status</span>
        <span className="text-[12px] font-medium text-tx-muted">
          {code}
        </span>

        <div className="ml-2 flex flex-wrap gap-1">
          {jobs.slice(0, 8).map((job) => {
            const on = active?.id === job.id;
            const color = statusColor(job.status);
            return (
              <button
                key={job.id}
                onClick={() => setSelected(job.id)}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11.5px] font-bold transition-all shadow-sm ${
                  on
                    ? "bg-brand-primary/10 border border-brand-primary/20 text-brand-primary"
                    : "border border-subtle text-tx-muted hover:text-tx-primary hover:bg-panel-muted"
                }`}
                title={`${jobTypeLabel(job.type)} · ${job.status}`}
              >
                <span
                  className="h-2 w-2 rounded-full shadow-sm"
                  style={{
                    background: color,
                    boxShadow: job.status === "running" ? `0 0 8px ${color}` : undefined,
                  }}
                />
                <span>{jobTypeLabel(job.type)}</span>
                {on ? (
                  <span className="text-[10px] uppercase tracking-widest opacity-80">{statusLabel(job.status)}</span>
                ) : null}
              </button>
            );
          })}
        </div>

        <span className="flex-1" />
        {canCancel && (
          <button
            type="button"
            onClick={cancelActiveJob}
            disabled={cancelling}
            aria-label="Cancel the active run"
            className="flex items-center gap-1.5 rounded-lg px-3 py-1 text-[11.5px] font-bold disabled:opacity-50 border border-status-error/30 text-status-error bg-status-error-soft shadow-sm hover:bg-status-error/10 transition-colors"
          >
            <Prohibit size={14} weight="bold" />
            {cancelling ? "Cancelling…" : "Cancel run"}
          </button>
        )}
        <button
          onClick={() => setTerminalOpen(false)}
          aria-label="Close run status"
          className="rounded-md p-1.5 text-tx-muted hover:bg-panel-muted hover:text-tx-primary transition-colors"
        >
          <X size={16} weight="bold" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        {error ? (
          <FetchError title="Could not load runs" error={error} onRetry={() => mutate()} />
        ) : active ? (
          <div className="flex h-full flex-col">
            {failureSummary && (
              <div className="mx-4 mt-4 rounded-xl px-4 py-3 bg-status-error-soft border border-status-error/30 shadow-sm">
                <p className="text-[13.5px] font-bold text-status-error tracking-tight">
                  {failureSummary.title}
                </p>
                <p className="mt-1 text-[12.5px] font-medium text-tx-secondary leading-relaxed">
                  {failureSummary.message}
                </p>
                {isAdminRole(userRole) && failureSummary.technical && (
                  <details className="mt-3">
                    <summary className="cursor-pointer text-[11px] font-bold uppercase tracking-widest text-tx-muted hover:text-tx-primary transition-colors outline-none">
                      Technical details
                    </summary>
                    <pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg p-3 text-[11px] font-mono bg-black/5 border border-black/10 text-status-error/90">
                      {failureSummary.technical}
                    </pre>
                  </details>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={() => setShowTechnicalLog((open) => !open)}
              className="mx-4 mt-3 flex items-center gap-1.5 self-start text-[12px] font-bold text-brand-primary hover:text-brand-primary/80 transition-colors"
            >
              {showTechnicalLog ? <CaretUp size={14} weight="bold" /> : <CaretDown size={14} weight="bold" />}
              {showTechnicalLog ? "Hide technical log" : "View technical log"}
            </button>

            {showTechnicalLog ? (
              <div className="mt-3 min-h-0 flex-1 border-t border-subtle">
                <div className="flex justify-end px-4 py-2 border-b border-subtle bg-panel">
                  <div className="flex overflow-hidden rounded-md border border-subtle bg-background shadow-sm">
                    <button
                      onClick={() => setRaw(false)}
                      aria-pressed={!raw}
                      className={`px-3 py-1 text-[11.5px] font-bold transition-colors ${
                        !raw
                          ? "bg-brand-primary/10 text-brand-primary"
                          : "text-tx-muted hover:text-tx-primary hover:bg-panel-muted"
                      }`}
                    >
                      Structured
                    </button>
                    <button
                      onClick={() => setRaw(true)}
                      aria-pressed={raw}
                      className={`px-3 py-1 text-[11.5px] font-bold border-l border-subtle transition-colors ${
                        raw
                          ? "bg-brand-primary/10 text-brand-primary"
                          : "text-tx-muted hover:text-tx-primary hover:bg-panel-muted"
                      }`}
                    >
                      Raw
                    </button>
                  </div>
                </div>
                <RunTerminal
                  key={`${active.id}-${raw}`}
                  jobId={active.id}
                  status={active.status}
                  raw={raw}
                />
              </div>
            ) : (
              <p className="px-4 py-6 text-[13px] font-medium text-tx-muted text-center">
                {active.status === "running"
                  ? "This run is in progress. Open the technical log to watch live output."
                  : active.status === "done"
                    ? "This run finished successfully."
                    : "Summary shown above. Open the technical log for full output."}
              </p>
            )}
          </div>
        ) : (
          <div className="px-4 py-6 text-[13px] font-medium text-tx-muted text-center">
            No runs yet for this bid.
          </div>
        )}
      </div>
    </div>
  );
}
