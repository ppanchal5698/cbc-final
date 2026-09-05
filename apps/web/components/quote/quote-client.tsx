"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { usePipelineJob } from "@/hooks/use-pipeline-job";
import {
  Table,
  Plus,
  Trash,
  ArrowRight,
  ArrowLeft,
  ArrowsClockwise,
  PencilLine,
  Clock,
  PhoneCall,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { AlternateBar } from "@/components/bids/alternate-bar";
import { JobFailedBanner } from "@/components/jobs/job-failed-banner";
import { useUiState } from "@/components/shell/ui-state";
import { formatMoney, formatPercent } from "@/lib/format";
import { belowBandTitle, isBelowBand } from "@/lib/margin";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { endpoints } from "@/lib/endpoints";
import { isAdminRole } from "@/lib/job-error";
import { taxSummary } from "@/lib/tax-display";
import type { AlternatesResponse, IntegrationsResponse, Job, QuoteLine, QuoteResponse } from "@/lib/types";

const TAX_OPTIONS = [
  { key: "OH", label: "Ohio 8.0%" },
  { key: "KY", label: "Kentucky 6.5%" },
  // "NONE" is a deliberate ruling; an unset value means the ship-to state decides.
  { key: "NONE", label: "No nexus" },
];

const COLUMNS = "140px minmax(200px,1fr) 60px 95px 85px 72px 120px 105px 30px";

/** An input that only commits on blur or Enter, so totals do not thrash per keystroke. */
function Cell({
  value,
  onCommit,
  align = "right",
  prefix,
  suffix,
  label,
  disabled,
}: {
  value: number | null;
  onCommit: (next: number | null) => void;
  align?: "left" | "right";
  prefix?: string;
  suffix?: string;
  label: string;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<{ from: number | null; text: string } | null>(null);

  // The draft follows the server value unless it is being typed into. Derived
  // from the value it was seeded off rather than synced in an effect, so a
  // background poll can never overwrite what someone is halfway through typing.
  const text = edit && (editing || edit.from === value) ? edit.text : value === null ? "" : String(value);

  function commit() {
    setEditing(false);
    const trimmed = text.trim();
    if (trimmed === "") {
      setEdit(null);
      if (value !== null) onCommit(null);
      return;
    }
    const parsed = Number(trimmed);
    if (Number.isNaN(parsed)) {
      toast.error(`${label} has to be a number`, { description: `"${trimmed}" is not one.` });
      setEdit(null);
      return;
    }
    setEdit(null);
    if (parsed === value) return;
    onCommit(parsed);
  }

  return (
    <span className="flex items-center rounded-md px-2 py-1.5 bg-background border border-subtle focus-within:ring-2 focus-within:ring-brand-border focus-within:border-brand-primary/30 transition-all shadow-sm">
      {prefix && (
        <span className="text-[11.5px] font-medium text-tx-muted mr-1.5">
          {prefix}
        </span>
      )}
      <input
        value={text}
        disabled={disabled}
        aria-label={label}
        inputMode="decimal"
        onChange={(event) => setEdit({ from: value, text: event.target.value })}
        onFocus={() => setEditing(true)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.currentTarget.blur();
          if (event.key === "Escape") {
            setEdit(null);
            setEditing(false);
            event.currentTarget.blur();
          }
        }}
        placeholder="—"
        className={`tnum w-full bg-transparent text-[13px] font-medium outline-none text-tx-primary placeholder:text-tx-muted ${align === "right" ? "text-right" : ""}`}
      />
      {suffix && (
        <span className="text-[11.5px] font-medium text-tx-muted ml-1.5">
          {suffix}
        </span>
      )}
    </span>
  );
}

export function QuoteClient({
  code,
  initialJob,
  autopilot = false,
}: {
  code: string;
  initialJob: Job | null;
  autopilot?: boolean;
}) {
  const router = useRouter();
  const { openNotes, userRole } = useUiState();
  const [busy, setBusy] = useState(false);
  const [alternate, setAlternate] = useState<string | null | undefined>(undefined);
  // NFR-8 is "below-band lines are flagged". The API flags them; until this
  // existed nothing showed the flag, so the guardrail ended at the API boundary.
  const [belowBandOnly, setBelowBandOnly] = useState(false);

  const { job, running } = usePipelineJob(code, initialJob);

  const { data, error, isLoading, mutate } = useSWR<QuoteResponse>(
    `/api/proxy/projects/${code}/quote`,
    proxyFetcher,
    { refreshInterval: running ? 4000 : 0 },
  );

  // Same SWR key as AlternateBar, so this is the same request, not a second one.
  const { data: alternateData } = useSWR<AlternatesResponse>(
    `/api/proxy/projects/${code}/alternates`,
    proxyFetcher,
  );

  const { data: integrations } = useSWR<IntegrationsResponse>(
    endpoints.integrations(),
    proxyFetcher,
  );

  const refresh = useCallback(() => {
    mutate();
    router.refresh();
  }, [mutate, router]);

  const filtering = alternate !== undefined || belowBandOnly;
  const groups = (data?.groups ?? [])
    .map((group) => {
      if (!filtering) return group;
      const lines = group.lines.filter(
        (line) =>
          (alternate === undefined ||
            (line.alternateGroup ?? null) === (alternate ?? null)) &&
          (!belowBandOnly || isBelowBand(line)),
      );
      return {
        ...group,
        lines,
        // Summing line extendeds the API already computed. No price, margin or
        // tax is recalculated here - those have one implementation, behind the API.
        subtotal: lines.reduce((sum, line) => sum + (line.extended ?? 0), 0),
      };
    })
    .filter((group) => group.lines.length > 0);

  const visibleLines = groups.reduce((sum, group) => sum + group.lines.length, 0);

  // Counted across every line the API returned, not the filtered view: a count
  // that shrank when you filtered by it would be reporting the filter.
  const belowBandTotal = (data?.groups ?? []).reduce(
    (sum, group) => sum + group.lines.filter(isBelowBand).length,
    0,
  );

  // When a group is selected the footer must show that group's money, not the
  // whole bid's. These totals are the API's own per-alternate figures.
  const selectedAlternate = filtering
    ? alternateData?.alternates.find((entry) => (entry.name ?? null) === (alternate ?? null))
    : undefined;
  const totals = data?.totals;
  const tax = totals ? taxSummary(totals) : null;

  async function patchLine(line: QuoteLine, body: Record<string, unknown>) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/lines/${line.id}`, {
        method: "PATCH",
        body,
      });
      mutate();
    } catch (problem) {
      toast.error("Could not save that", { description: errorMessage(problem) });
    }
  }

  async function deleteLine(line: QuoteLine) {
    if (!window.confirm(`Remove "${line.description}" from the quote?`)) return;
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/lines/${line.id}`, {
        method: "DELETE",
      });
      toast.success("Line removed");
      mutate();
    } catch (problem) {
      toast.error("Could not remove that line", { description: errorMessage(problem) });
    }
  }

  async function addLine() {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/lines`, {
        body: { description: "New line", division: "08 11 00", qty: 1 },
      });
      toast.success("Line added", { description: "Set its cost and margin." });
      mutate();
    } catch (problem) {
      toast.error("Could not add a line", { description: errorMessage(problem) });
    }
  }

  async function setFreight(value: number | null) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/settings`, {
        method: "PATCH",
        body: { freight: value },
      });
      toast.success(value ? "Freight added to the quote" : "Freight back to TBD");
      mutate();
    } catch (problem) {
      toast.error("Could not update freight", { description: errorMessage(problem) });
    }
  }

  async function setTax(state: string) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/settings`, {
        method: "PATCH",
        body: { taxJurisdiction: state },
      });
      mutate();
    } catch (problem) {
      toast.error("Could not update tax jurisdiction", { description: errorMessage(problem) });
    }
  }

  async function continueToProposal() {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/continue-to-proposal`);
      toast.success("Proposal queued for Claude");
      refresh();
      router.push(`/bids/${code}/proposal`);
    } catch (problem) {
      toast.error("Could not hand off to the proposal", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function rerunPricing() {
    if (
      autopilot &&
      (data?.lineCount ?? 0) > 0 &&
      !window.confirm(
        "Autopilot already priced this bid. Re-run pricing only if you changed the take-off or need a fresh pass.",
      )
    ) {
      return;
    }
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}/line-items/continue-to-quote`);
      toast.success("Pricing queued");
      refresh();
    } catch (problem) {
      toast.error("Could not queue pricing", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <main className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
        <AlternateBar code={code} active={alternate} onChange={setAlternate} showTotals />

        {(job?.status === "failed" || job?.status === "dead") && job && (
          <JobFailedBanner
            job={job}
            role={userRole}
            stage="quote"
            onAction={(action) => {
              if (action.label === "Re-run pricing") rerunPricing();
              else if (action.label === "Notify your admin") {
                toast.message("Ask your administrator to configure the AI provider in Settings.");
              }
            }}
          />
        )}

        {running && (
          <div className="anim-fadein rounded-xl px-4 py-3 text-[13px] font-medium bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm">
            Claude is pricing the lines. Totals refresh as matches land.
          </div>
        )}

        {integrations?.p21 && !integrations.p21.connected && (
          <p className="rounded-xl px-4 py-3.5 text-[12.5px] font-medium leading-relaxed bg-panel-muted border border-subtle text-tx-secondary shadow-sm">
            {integrations.p21.note}{" "}
            Ask your administrator if you expected purchase-order costs.
            {isAdminRole(userRole) && integrations.p21.adminNote && (
              <span className="mt-2 block text-[11.5px] text-tx-muted">
                {integrations.p21.adminNote}
              </span>
            )}
          </p>
        )}

        <div className="flex flex-col rounded-xl bg-panel border border-subtle shadow-sm">
          <div className="flex flex-wrap items-center gap-4 border-b border-subtle px-5 py-4 bg-panel">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-primary/10 text-brand-primary border border-brand-primary/20 shadow-sm">
              <Table size={20} weight="duotone" />
            </span>
            <span className="flex flex-col leading-tight gap-1">
              <span className="text-[16px] font-bold tracking-tight">Quote</span>
              <span className="text-[12.5px] font-medium text-tx-muted">
                {data?.lineCount ?? 0} lines · margin follows the category divisors
                {totals?.margin ? ` · ${formatPercent(totals.margin)} blended` : ""} · every figure
                below is editable
              </span>
            </span>

            {belowBandTotal > 0 && (
              <button
                type="button"
                onClick={() => setBelowBandOnly((on) => !on)}
                aria-pressed={belowBandOnly}
                className={`rounded-lg px-3 py-1.5 text-[12px] font-bold transition-all shadow-sm ${
                  belowBandOnly
                    ? "bg-status-error text-white border-status-error hover:bg-status-error/90"
                    : "bg-background text-status-error border-status-error hover:bg-status-error-soft border"
                }`}
                title="Lines whose margin is under its product-type floor"
              >
                {belowBandTotal} below band
              </button>
            )}

            {!!data?.edited?.count && (
              <span className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-bold bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
                <PencilLine size={14} weight="fill" />
                {data.edited.count} line{data.edited.count === 1 ? "" : "s"} edited by hand
              </span>
            )}

            {!!data?.lapsedCount && (
              <span
                className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-bold bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm"
                title={`Priced from a book past its ${data.reviewWindowMonths ?? 24}-month review window`}
              >
                <Clock size={14} weight="fill" />
                {data.lapsedCount} lapsed
              </span>
            )}

            <span className="flex-1" />

            <div className="flex flex-wrap gap-1.5">
              {TAX_OPTIONS.map((option) => {
                const active = (totals?.taxJurisdiction ?? "") === option.key;
                return (
                  <button
                    key={option.key}
                    onClick={() => setTax(option.key)}
                    aria-pressed={active}
                    className={`rounded-lg px-3 py-1.5 text-[12px] font-bold transition-all shadow-sm ${
                      active
                        ? "bg-brand-primary/10 text-brand-primary border border-brand-primary/20"
                        : "bg-background text-tx-secondary border border-subtle hover:bg-panel-muted hover:text-tx-primary"
                    }`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>

            <button
              onClick={addLine}
              className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
            >
              <Plus size={14} weight="bold" />
              Add line
            </button>
          </div>

          {running && (
            <div className="anim-fadein relative overflow-hidden px-5 py-3 text-[13px] font-bold bg-status-warning-soft text-status-warning shadow-inner">
              <span className="anim-sweep" />
              Claude is matching and pricing the confirmed openings.
            </div>
          )}

          <div className="overflow-x-auto">
            <div style={{ minWidth: 940 }}>
              <div
                className="grid gap-4 border-b border-subtle px-5 py-3 text-[11px] font-bold uppercase tracking-widest text-tx-muted bg-panel-muted"
                style={{ gridTemplateColumns: COLUMNS }}
              >
                <span>Part</span>
                <span>Description</span>
                <span className="text-right">Qty</span>
                <span className="text-right">Cost</span>
                <span className="text-right">Sell</span>
                <span className="text-right">Margin</span>
                <span>Basis</span>
                <span className="text-right">Extended</span>
                <span />
              </div>

              {error ? (
                <div className="grid place-items-center gap-3 px-6 py-20 text-center">
                  <span className="text-[14px] font-bold text-status-error bg-status-error-soft px-4 py-2 rounded-lg border border-status-error/30 shadow-sm">
                    Could not load the quote
                  </span>
                  <span className="max-w-[440px] text-[13px] font-medium text-tx-secondary mt-1">
                    {errorMessage(error)}
                  </span>
                  <button
                    onClick={() => mutate()}
                    className="mt-2 rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
                  >
                    Try again
                  </button>
                </div>
              ) : isLoading && !data ? (
                <div className="grid place-items-center px-6 py-20 text-center">
                  <span className="text-[13.5px] font-medium text-tx-muted animate-pulse">
                    Loading the priced lines…
                  </span>
                </div>
              ) : groups.length === 0 ? (
                <div className="grid place-items-center gap-2 px-6 py-20 text-center">
                  <span className="text-[15px] font-bold text-tx-primary">
                    {running
                      ? "Pricing in progress…"
                      : filtering && data?.lineCount
                        ? "Nothing in this group yet"
                        : "Nothing priced yet"}
                  </span>
                  <span className="max-w-[440px] text-[13px] font-medium text-tx-secondary">
                    {running
                      ? "Claude is working through the catalog and the price books."
                      : filtering && data?.lineCount
                        ? "Move lines into this alternate on the extraction step, or add them by hand."
                        : "Confirm the openings on the extraction step, then hand off to pricing."}
                  </span>
                </div>
              ) : (
                groups.map((group) => (
                  <div key={group.division}>
                    <div className="flex items-center gap-3 px-5 py-3.5 bg-panel-muted border-b border-subtle/50">
                      <span className="text-[14px] font-bold text-tx-primary tracking-tight">{group.division}</span>
                      <span className="text-[12px] font-medium text-tx-muted">
                        {group.lines.length} line{group.lines.length === 1 ? "" : "s"}
                      </span>
                      <span className="flex-1" />
                      <span className="tnum text-[14px] font-bold text-brand-primary">
                        ${formatMoney(group.subtotal)}
                      </span>
                    </div>

                    {group.lines.map((line) => (
                      <div
                        key={line.id}
                        className={`grid items-center gap-4 border-b border-subtle px-5 py-3.5 last:border-b-0 hover:bg-background/50 transition-colors ${line.addedByHand ? "border-l-4 border-l-status-error" : ""}`}
                        style={{ gridTemplateColumns: COLUMNS }}
                      >
                        <span className="truncate text-[13px] font-medium text-tx-secondary">
                          {line.part ?? "—"}
                        </span>

                        <span className="min-w-0">
                          <span className="block truncate text-[13.5px] font-semibold text-tx-primary" title={line.description}>
                            {line.description}
                          </span>
                          {(line.marginOverridden || line.addedByHand) && (
                            <span className="text-[11.5px] font-medium text-status-error mt-0.5 block">
                              {line.addedByHand ? "added by hand" : "margin overridden"}
                              {line.overrideReason ? ` · ${line.overrideReason}` : ""}
                            </span>
                          )}
                          {isBelowBand(line) && (
                            <span
                              className="inline-block mt-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-status-error border border-status-error bg-status-error-soft shadow-sm"
                              title={belowBandTitle(line)}
                            >
                              below band
                            </span>
                          )}
                        </span>

                        <Cell
                          value={line.qty}
                          label={`Quantity for ${line.description}`}
                          onCommit={(next) => patchLine(line, { qty: next ?? 1 })}
                        />
                        <Cell
                          value={line.cost}
                          prefix="$"
                          label={`Cost for ${line.description}`}
                          onCommit={(next) => patchLine(line, { cost: next })}
                        />

                        <span className="tnum text-right text-[13px] font-bold">
                          {line.sell === null ? (
                            <span className="flex flex-col items-end gap-0.5">
                              <span className="rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning shadow-sm">
                                {line.priceStatus ?? "MANUAL"}
                              </span>
                              {(line.costSource === "DISTRIBUTOR_MANUAL" ||
                                line.costSource === "MANUAL") && (
                                <span className="text-[10px] font-medium text-status-warning">
                                  Price may be out of date — refresh
                                </span>
                              )}
                            </span>
                          ) : (
                            formatMoney(line.sell)
                          )}
                        </span>

                        <Cell
                          // Shown to a tenth rather than rounded to a whole
                          // percent: a 27.5% band displayed as "28" and then
                          // committed back was a silent half-point of margin.
                          value={line.margin === null ? null : Number((line.margin * 100).toFixed(1))}
                          suffix="%"
                          label={`Margin for ${line.description}`}
                          onCommit={(next) =>
                            patchLine(line, {
                              margin: next === null ? null : Math.min(Math.max(next, 0), 99) / 100,
                              overrideReason: "edited on the quote grid",
                            })
                          }
                        />

                        <span className="min-w-0">
                          <span
                            className="block truncate text-[12px] font-medium text-tx-secondary"
                            title={
                              [line.basis, line.multiplierTier, line.multiplierEffectiveDate]
                                .filter(Boolean)
                                .join(" · ") || undefined
                            }
                          >
                            {line.basis ?? "—"}
                          </span>
                          {line.lapsed && (
                            <span
                              className="inline-block mt-0.5 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning shadow-sm"
                              title={`Price book effective ${line.multiplierEffectiveDate} — past the ${data?.reviewWindowMonths ?? 24}-month review window`}
                            >
                              lapsed
                            </span>
                          )}
                        </span>

                        <span className="tnum text-right text-[13.5px] font-bold text-tx-primary">
                          {line.extended === null ? "—" : `$${formatMoney(line.extended)}`}
                        </span>

                        <button
                          onClick={() => deleteLine(line)}
                          aria-label={`Remove ${line.description}`}
                          className="text-tx-muted hover:text-status-error transition-colors p-1.5 rounded-md hover:bg-status-error-soft"
                        >
                          <Trash size={16} weight="fill" />
                        </button>
                      </div>
                    ))}
                  </div>
                ))
              )}
            </div>
          </div>

          {totals && (
            <div className="flex flex-wrap items-end gap-8 border-t border-subtle px-6 py-6 bg-panel-muted rounded-b-xl">
              <span className="min-w-[220px] flex-1 text-[12.5px] font-medium text-tx-muted leading-relaxed">
                Lines with a magenta rule were added by hand. Divisors come from the margin sheet.
                {totals.unpricedLines > 0 && (
                  <>
                    {" "}
                    <strong className="text-status-error font-bold">
                      {totals.unpricedLines === 1
                        ? "1 line still needs a price."
                        : `${totals.unpricedLines} lines still need a price.`}
                    </strong>
                  </>
                )}
              </span>

              {[
                ["Cost", `$${formatMoney(totals.cost)}`, "text-tx-secondary"],
                ["Margin", formatPercent(totals.margin), "text-brand-primary"],
              ].map(([label, value, colorClass]) => (
                <span key={label} className="flex flex-col items-end leading-tight gap-1">
                  <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    {label}
                  </span>
                  <span className={`tnum text-[16px] font-bold ${colorClass}`}>
                    {value}
                  </span>
                </span>
              ))}

              {tax && (
                <span className="flex flex-col items-end leading-tight gap-1">
                  <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    {tax.label}
                  </span>
                  <span className={`tnum text-[16px] font-bold ${tax.muted ? "text-tx-muted" : "text-tx-secondary"}`}>
                    {tax.value}
                  </span>
                </span>
              )}

              <span className="flex flex-col items-end leading-tight gap-1">
                <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                  Freight
                </span>
                <Cell value={totals.freight} prefix="$" label="Freight" onCommit={setFreight} />
                <span className="mt-1 text-[11px] font-medium text-tx-muted">
                  {totals.freight ? "quoted on this bid" : "TBD at estimate stage"}
                </span>
              </span>

              <span className="flex flex-col items-end leading-tight gap-1">
                <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                  {/* Showing the whole bid's total above a filtered list was
                      the screen telling two different stories at once. */}
                  {selectedAlternate ? `${selectedAlternate.label} total` : "Sell total"}
                </span>
                <span className="tnum text-[28px] font-bold tracking-tight text-tx-primary">
                  $
                  {formatMoney(
                    selectedAlternate ? selectedAlternate.grandTotal : totals.grandTotal,
                  )}
                </span>
                {filtering && (
                  <span className="mt-1 text-[11px] font-medium text-tx-muted">
                    {visibleLines} of {data?.lineCount ?? 0} lines · whole bid $
                    {formatMoney(totals.grandTotal)}
                  </span>
                )}
              </span>

              {tax?.hint && (
                <span className="w-full text-right text-[11.5px] font-medium text-tx-muted mt-2">
                  {tax.hint}
                </span>
              )}

              {(data?.lineCount ?? 0) === 0 && (
                <span className="w-full text-right text-[11.5px] font-medium text-tx-muted mt-2">
                  Totals update once lines are priced.
                </span>
              )}
            </div>
          )}
        </div>
      </main>

      <footer className="flex flex-wrap items-center gap-4 border-t border-subtle px-6 py-4 bg-background">
        <a
          href={`/bids/${code}/extraction`}
          className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-bold no-underline border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
        >
          <ArrowLeft size={16} weight="bold" />
          Back
        </a>
        <button
          onClick={() => openNotes("Quote")}
          className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
        >
          <PhoneCall size={16} weight="fill" />
          Log a call
        </button>

        <span className="min-w-[200px] flex-1 text-[13px] font-medium text-tx-secondary">
          Cost, sell and margin are all editable. Overrides are logged against your name.
        </span>
        <button
          onClick={() => mutate()}
          className="flex items-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
        >
          <ArrowsClockwise size={16} weight="bold" />
          Refresh
        </button>
        <button
          onClick={continueToProposal}
          disabled={busy || !totals || totals.unpricedLines > 0}
          className="flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13px] font-bold disabled:opacity-50 transition-all bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
        >
          Build proposal
          <ArrowRight size={16} weight="bold" />
        </button>
      </footer>
    </>
  );
}
