"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import {
  ArrowsClockwise,
  Checks,
  FilePdf,
  ListChecks,
  ArrowRight,
  ArrowLeft,
  Lightning,
  X,
  PhoneCall,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import dynamic from "next/dynamic";

import { AlternateBar } from "@/components/bids/alternate-bar";
import { BulkBar } from "@/components/extraction/bulk-bar";
import { LineItemRow, ROW_COLUMNS } from "@/components/extraction/line-item-row";
import { PartComposer } from "@/components/extraction/part-composer";
import { SpecialtiesTakeoffPanel } from "@/components/extraction/specialties-takeoff-panel";
import { JobFailedBanner } from "@/components/jobs/job-failed-banner";
import { useRowKeys } from "@/hooks/use-row-keys";
import { useUiState } from "@/components/shell/ui-state";
import { usePipelineJob } from "@/hooks/use-pipeline-job";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type {
  AlternateAssignResult,
  AlternatesResponse,
  BidDocument,
  BulkResult,
  Job,
  LineItem,
  LineItemsResponse,
} from "@/lib/types";

// pdf.js touches DOMMatrix at module scope, so the viewer cannot be evaluated
// during server rendering.
const SheetViewer = dynamic(
  () => import("@/components/extraction/sheet-viewer").then((m) => m.SheetViewer),
  {
    ssr: false,
    loading: () => (
      <aside className="grid h-[320px] w-full shrink-0 place-items-center rounded-xl xl:h-auto xl:w-[clamp(380px,34vw,560px)] bg-panel border border-subtle shadow-sm">
        <span className="text-[13px] font-medium text-tx-muted animate-pulse">
          Loading the sheet viewer…
        </span>
      </aside>
    ),
  },
);

const FILTERS = [
  { key: "all", label: "All", countKey: "all" },
  { key: "needs_look", label: "Needs a look", countKey: "needs_look" },
  { key: "duplicate", label: "Duplicates", countKey: "duplicate" },
  { key: "by_hand", label: "By hand", countKey: "by_hand" },
  { key: "clear", label: "Clear", countKey: "clear" },
] as const;

export function ExtractionClient({
  code,
  documents,
  initialJob,
  autopilot = false,
}: {
  code: string;
  documents: BidDocument[];
  initialJob: Job | null;
  autopilot?: boolean;
}) {
  const router = useRouter();
  const { openNotes, focusMode, userRole } = useUiState();
  const [filter, setFilter] = useState<string>("all");
  const [selected, setSelected] = useState<LineItem | null>(null);
  const [showSheet, setShowSheet] = useState(true);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [alternate, setAlternate] = useState<string | null | undefined>(undefined);
  const [runDismissed, setRunDismissed] = useState<string | null>(null);
  // Selection is scoped to the active filter/alternate; reset when the scope changes.
  const pickScope = `${filter}:${alternate === undefined ? "" : (alternate ?? "")}`;
  const [pickScopeKey, setPickScopeKey] = useState(pickScope);
  if (pickScopeKey !== pickScope) {
    setPickScopeKey(pickScope);
    setPicked(new Set());
  }

  const { job, running } = usePipelineJob(code, initialJob);

  const alternateQuery =
    alternate === undefined ? "" : `&alternate=${encodeURIComponent(alternate ?? "")}`;

  const { data, error, isLoading, mutate } = useSWR<LineItemsResponse>(
    `/api/proxy/projects/${code}/line-items?filter=${filter}${alternateQuery}`,
    proxyFetcher,
    { refreshInterval: running ? 4000 : 0 },
  );

  const { data: alternateData, mutate: mutateAlternates } = useSWR<AlternatesResponse>(
    `/api/proxy/projects/${code}/alternates`,
    proxyFetcher,
  );

  const refresh = useCallback(() => {
    mutate();
    mutateAlternates();
    router.refresh();
  }, [mutate, mutateAlternates, router]);

  const items = data?.lineItems ?? [];
  const counts = data?.counts;
  const needsLook = counts?.needs_look ?? 0;

  const togglePick = useCallback((item: LineItem) => {
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.add(item.id);
      return next;
    });
  }, []);

  const confirmOne = useCallback(
    async (item: LineItem) => {
      try {
        await proxyMutate(`/api/proxy/projects/${code}/line-items/${item.id}/confirm`);
        mutate();
      } catch (problem) {
        toast.error("Could not confirm that line", { description: errorMessage(problem) });
      }
    },
    [code, mutate],
  );

  const { cursorId } = useRowKeys<LineItem>({
    rows: items,
    onConfirm: confirmOne,
    onToggleSelect: togglePick,
    onOpen: (item) => {
      setSelected(item);
      setShowSheet(true);
    },
  });

  async function assignAlternate(alternateName: string | null) {
    if (picked.size === 0) return;
    setBusy(true);
    try {
      const result = await proxyMutate<AlternateAssignResult>(
        `/api/proxy/projects/${code}/alternates/assign`,
        { body: { ids: [...picked], alternate: alternateName, scope: "line-items" } },
      );
      toast.success(`Moved ${result.moved} line${result.moved === 1 ? "" : "s"}`);
      setPicked(new Set());
      refresh();
    } catch (problem) {
      toast.error("Could not move those lines", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function bulk(action: "confirm" | "delete") {
    // Removing a batch of lines is not undoable from this screen.
    if (
      action === "delete" &&
      !window.confirm(
        `Remove ${picked.size} line${picked.size === 1 ? "" : "s"} from this bid? This cannot be undone here.`,
      )
    ) {
      return;
    }

    setBusy(true);
    try {
      const result = await proxyMutate<BulkResult>(
        `/api/proxy/projects/${code}/line-items/bulk`,
        { body: { ids: [...picked], action } },
      );
      toast.success(
        action === "confirm" ? `${result.affected} confirmed` : `${result.affected} removed`,
      );
      setPicked(new Set());
      refresh();
    } catch (problem) {
      toast.error("That did not go through", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  const progressLabel = useMemo(() => {
    if (!counts) return "loading…";
    return `${counts.clear} of ${counts.all} items clear`;
  }, [counts]);

  async function post(path: string, success: string, then?: () => void) {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}${path}`);
      toast.success(success);
      refresh();
      then?.();
    } catch (problem) {
      toast.error("That did not go through", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <main className="flex min-h-0 flex-1 flex-col gap-4 overflow-hidden p-4 xl:flex-row">
        <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-col rounded-xl bg-panel border border-subtle shadow-sm">
            <div className="flex flex-wrap items-center gap-4 border-b border-subtle px-5 py-4 bg-background/30">
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-brand-primary/10 text-brand-primary shadow-sm border border-brand-primary/20">
                <ListChecks size={20} weight="duotone" />
              </span>
              <span className="flex flex-col leading-tight">
                <span className="text-[15px] font-bold text-tx-primary tracking-tight">Line items</span>
                <span className="text-[12px] font-medium text-tx-muted mt-0.5">
                  {progressLabel} · <b>J</b> <b>K</b> to move · <b>space</b> select ·{" "}
                  <b>&#8629;</b> confirm · <b>O</b> open the sheet · <b>C</b> log a call
                </span>
              </span>

              <span className="flex-1" />

              <button
                onClick={() => post("/line-items/rerun", "Claude is re-reading the drawings")}
                disabled={busy || running}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors disabled:opacity-50 shadow-sm bg-background"
              >
                <ArrowsClockwise size={16} weight="bold" />
                Re-run extraction
              </button>

              {needsLook > 0 && (
                <button
                  onClick={() => post("/line-items/confirm-all", "Everything flagged is confirmed")}
                  disabled={busy}
                  className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold disabled:opacity-50 transition-colors bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
                >
                  <Checks size={16} weight="bold" />
                  Confirm all {needsLook}
                </button>
              )}

              <button
                onClick={() => setShowSheet((current) => !current)}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-background"
              >
                <FilePdf size={16} weight="bold" />
                {showSheet ? "Hide the sheet" : "Open the sheet"}
              </button>
            </div>

            <div className="flex flex-wrap gap-2 px-4 py-3 bg-panel-muted/20">
              {FILTERS.map((entry) => {
                const active = filter === entry.key;
                const count = counts?.[entry.countKey as keyof typeof counts] ?? 0;
                return (
                  <button
                    key={entry.key}
                    onClick={() => setFilter(entry.key)}
                    className={`flex items-center gap-2 rounded-lg px-4 py-1.5 text-[13px] font-bold transition-all shadow-sm ${
                      active
                        ? "bg-panel border border-subtle text-tx-primary"
                        : "bg-transparent text-tx-secondary hover:bg-panel hover:text-tx-primary border border-transparent"
                    }`}
                  >
                    {entry.label}
                    <span className={`tnum ${active ? "text-brand-primary" : "text-tx-muted"}`}>
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>

          <AlternateBar code={code} active={alternate} onChange={setAlternate} />

          <SpecialtiesTakeoffPanel code={code} />

          {running && (
            <div className="anim-fadein relative overflow-hidden rounded-xl px-5 py-4 text-[13px] font-medium bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm">
              <span className="anim-sweep opacity-50" />
              Claude is reading the bid set. Lines appear here as they are found.
            </div>
          )}

          {job?.status === "done" && job.note && runDismissed !== job.id && !focusMode && (
            <div className="anim-fadein flex items-center gap-3 rounded-xl px-5 py-3.5 bg-status-success-soft border border-status-success/30 text-status-success shadow-sm">
              <Lightning size={20} weight="fill" />
              <span className="flex flex-1 flex-col leading-tight gap-0.5">
                <span className="text-[13px] font-bold tracking-tight">Last pass complete</span>
                <span className="text-[12.5px] font-medium opacity-90">{job.note}</span>
              </span>
              <button onClick={() => setRunDismissed(job.id)} aria-label="Dismiss the run status" className="p-1 rounded hover:bg-status-success/10 transition-colors">
                <X size={16} weight="bold" />
              </button>
            </div>
          )}

          {(job?.status === "failed" || job?.status === "dead") && job && (
            <JobFailedBanner
              job={job}
              role={userRole}
              stage="extraction"
              onAction={(action) => {
                if (action.label === "Add lines by hand") {
                  document.getElementById("add-by-hand")?.scrollIntoView({ behavior: "smooth" });
                } else if (action.label === "Re-run extraction") {
                  post("/line-items/rerun", "Claude is re-reading the drawings");
                } else if (action.label === "Notify your admin") {
                  toast.message("Ask your administrator to configure the AI provider in Settings.");
                }
              }}
            />
          )}

          <div className="min-h-[200px] flex-1 overflow-auto rounded-xl bg-panel border border-subtle shadow-inner">
            <div style={{ minWidth: 820 }}>
            <div
              className="sticky top-0 z-20 grid gap-3 border-b border-subtle px-5 py-3 text-[11px] font-bold uppercase tracking-widest bg-panel/95 backdrop-blur text-tx-muted shadow-sm"
              style={{ gridTemplateColumns: ROW_COLUMNS }}
            >
              <span>
                <input
                  type="checkbox"
                  aria-label="Select all"
                  checked={items.length > 0 && picked.size === items.length}
                  onChange={() =>
                    setPicked(
                      picked.size === items.length ? new Set() : new Set(items.map((i) => i.id)),
                    )
                  }
                />
              </span>
              <span />
              <span>Mark</span>
              <span>Description</span>
              <span>Size</span>
              <span>Qty</span>
              <span>HW set</span>
              <span className="text-right">Status</span>
            </div>

            {error ? (
              <div className="grid place-items-center gap-2 px-6 py-20 text-center">
                <span className="text-[14px] font-bold text-status-error">
                  Could not load the line items
                </span>
                <span className="max-w-[420px] text-[13px] font-medium text-tx-secondary">
                  {errorMessage(error)}
                </span>
                <button
                  onClick={() => mutate()}
                  className="mt-2 rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-background"
                >
                  Try again
                </button>
              </div>
            ) : isLoading && !data ? (
              <div className="grid place-items-center px-6 py-20 text-center">
                <span className="text-[13px] font-medium text-tx-muted animate-pulse">
                  Loading the openings…
                </span>
              </div>
            ) : items.length === 0 ? (
              <div className="grid place-items-center gap-2 px-6 py-20 text-center">
                <span className="text-[14px] font-bold text-tx-primary">
                  {running ? "Reading the bid set…" : "Nothing here yet"}
                </span>
                <span className="max-w-[420px] text-[13px] font-medium text-tx-secondary">
                  {running
                    ? "Claude is working through the schedules and elevations."
                    : filter === "all"
                      ? "Upload a plan set on the intake step, and the openings are read for you."
                      : "No lines match this filter."}
                </span>
              </div>
            ) : (
              items.map((item) => (
                <LineItemRow
                  key={item.id}
                  item={item}
                  code={code}
                  selected={selected?.id === item.id}
                  focused={cursorId === item.id}
                  picked={picked.has(item.id)}
                  onPick={() => togglePick(item)}
                  onSelect={(next) => {
                    setSelected(next);
                    if (next) setShowSheet(true);
                  }}
                  onChanged={refresh}
                />
              ))
            )}
            </div>
            <BulkBar
              selected={picked.size}
              total={items.length}
              busy={busy}
              alternates={alternateData?.alternates}
              onSelectAll={() => setPicked(new Set(items.map((i) => i.id)))}
              onConfirm={() => bulk("confirm")}
              onRemove={() => bulk("delete")}
              onClear={() => setPicked(new Set())}
              onAssignAlternate={assignAlternate}
            />
          </div>

          <div id="add-by-hand">
          <PartComposer code={code} onAdded={refresh} />
          </div>
        </section>

        {showSheet && (
          <SheetViewer
            code={code}
            documents={documents}
            selected={selected}
            onClose={() => setShowSheet(false)}
          />
        )}
      </main>

      <footer className="flex shrink-0 flex-wrap items-center gap-4 border-t border-subtle px-6 py-4 bg-background">
        <a
          href={`/bids/${code}/intake`}
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold no-underline border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-panel"
        >
          <ArrowLeft size={16} weight="bold" />
          Back
        </a>

        <button
          onClick={() => openNotes("Extraction & entry")}
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-panel"
        >
          <PhoneCall size={16} weight="bold" />
          Log a call
        </button>

        <span className="min-w-[200px] flex-1 text-[13px] font-medium text-tx-secondary text-center sm:text-left">
          {needsLook > 0
            ? `${needsLook} item${needsLook === 1 ? "" : "s"} need a look. Open one, check it against the sheet, confirm.`
            : counts?.all
              ? "Every line has been checked."
              : "No lines yet."}
        </span>

        <button
          onClick={() => post("/line-items/rerun", "Re-extraction queued")}
          disabled={busy || running}
          className="flex items-center gap-2 rounded-lg px-4 py-2 text-[12.5px] font-bold disabled:opacity-50 border border-subtle text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm bg-panel"
        >
          <ArrowsClockwise size={16} weight="bold" />
          Re-run extraction
        </button>

        <button
          onClick={() => {
            if (
              autopilot &&
              !window.confirm(
                "This bid ran on autopilot. Re-run pricing only if you changed the take-off or need a fresh pass.",
              )
            ) {
              return;
            }
            post("/line-items/continue-to-quote", "Pricing queued for Claude", () =>
              router.push(`/bids/${code}/quote`),
            );
          }}
          disabled={busy || running || !counts?.all}
          className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13px] font-bold disabled:opacity-50 transition-all bg-brand-primary text-white hover:bg-brand-primary/90 shadow-md hover:shadow-lg"
        >
          Continue to Quote
          <ArrowRight size={16} weight="bold" />
        </button>
      </footer>
    </>
  );
}
