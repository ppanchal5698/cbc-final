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
  CaretDown,
  CaretRight,
  ArrowsInLineVertical,
  ArrowsOutLineVertical,
  ClockCounterClockwise,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { AlternateBar } from "@/components/bids/alternate-bar";
import { VendorRfqsPanel } from "@/components/quote/vendor-rfqs-panel";
import { CustomLineDialog } from "@/components/quote/custom-line-dialog";
import { JobFailedBanner } from "@/components/jobs/job-failed-banner";
import { useUiState } from "@/components/shell/ui-state";
import { formatMoney, formatPercent } from "@/lib/format";
import { belowBandTitle, isBelowBand, wouldBeBelowBand } from "@/lib/margin";
import { Nomenclature } from "@/components/quote/nomenclature";
import { slotOf, slotRank } from "@/lib/slot";
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
  // FR-18: a buyer with an exemption certificate on file. Prints as exempt.
  { key: "EXEMPT", label: "Tax exempt" },
];

// Where a cost came from (requirements 5.2): the ladder's own rungs, and the paths
// an estimator prices by hand - a distributor, the maker's website, a vendor quote.
const COST_SOURCES = [
  "P21_LAST_PO",
  "SPECIAL_NET",
  "CATALOG_BASELINE",
  "LIST_X_MULTIPLIER",
  "DISTRIBUTOR_MANUAL",
  "MANUFACTURER_WEBSITE",
  "VENDOR_RFQ",
  "MANUAL",
];

// Component first: an estimator checks a set in the order it is written.
const COLUMNS =
  "96px minmax(150px,1.1fr) minmax(200px,2fr) 56px 95px 120px 72px minmax(110px,1fr) 100px 32px";

// Why a margin is not the band's (requirements 5.1) - the API's codes, in its words.
const OVERRIDE_REASONS: [string, string][] = [
  ["special_customer", "Special customer or brand margin"],
  ["distributor_buy", "Distributor buy"],
  ["competitive", "Competitive bid"],
  ["volume", "Volume or repeat work"],
  ["estimator_judgment", "Estimator judgment"],
  ["other", "Other"],
];

// FR-6a: the requirements' green / amber / red / blocked, from the API's verdict.
const FRESHNESS: Record<string, { label: string; tone: string }> = {
  fresh: { label: "current", tone: "text-status-success bg-status-success-soft border-status-success/30" },
  aging: { label: "aging", tone: "text-status-warning bg-status-warning-soft border-status-warning/30" },
  unknown: { label: "undated", tone: "text-status-warning bg-status-warning-soft border-status-warning/30" },
  unreliable: { label: "re-verify", tone: "text-status-error bg-status-error-soft border-status-error/30" },
  stale: { label: "blocked", tone: "text-status-error bg-status-error-soft border-status-error" },
  future_dated: { label: "future date", tone: "text-status-error bg-status-error-soft border-status-error/30" },
};

/** A line copied from a prior bid that nobody has kept yet (FR-1d). */
function isCarried(line: QuoteLine): boolean {
  return line.flags.includes("carried_from_prior");
}

function formatCostSourceLabel(source?: string | null): string {
  if (!source) return "MANUAL";
  switch (source) {
    case "DISTRIBUTOR_MANUAL":
      return "Dist. Manual";
    case "VENDOR_RFQ":
      return "Vendor RFQ";
    case "P21_LAST_PO":
      return "P21 PO";
    case "LIST_X_MULTIPLIER":
      return "List × Mult";
    case "SPECIAL_NET":
      return "Special Net";
    case "BOOK_PRICE":
      return "Book Price";
    case "CATALOG_BASELINE":
      return "Catalog";
    case "MANUFACTURER_WEBSITE":
      return "Mfr website";
    case "MANUAL":
      return "Manual";
    default:
      return source.replace(/_/g, " ");
  }
}

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
  const [customOpen, setCustomOpen] = useState(false);
  const [alternate, setAlternate] = useState<string | null | undefined>(undefined);
  // NFR-8 is "below-band lines are flagged". The API flags them; until this
  // existed nothing showed the flag, so the guardrail ended at the API boundary.
  const [belowBandOnly, setBelowBandOnly] = useState(false);
  // Collapsed openings, by group key. Nothing is collapsed until asked.
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleGroup = useCallback((key: string) => {
    setCollapsed((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const { job, running } = usePipelineJob(code, initialJob);

  const { data, error, isLoading, mutate } = useSWR<QuoteResponse>(
    `/api/proxy/projects/${code}/quote`,
    proxyFetcher,
    { refreshInterval: running ? 4000 : 0 },
  );

  // Same SWR key as AlternateBar, so this is the same request, not a second one.
  const { data: alternateData, mutate: mutateAlternates } = useSWR<AlternatesResponse>(
    `/api/proxy/projects/${code}/alternates`,
    proxyFetcher,
  );
  // FR-14: the groups a line may sit in, and the substitutions a base line may be replaced in.
  const lineGroups = (alternateData?.alternates ?? []).filter((entry) => !entry.isBase);
  const substitutions = lineGroups.filter((entry) => entry.kind === "substitution");

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

  // FR-1d: lines a templated bid copied from a prior one, until an estimator
  // keeps them. The proposal waits on them, so a leftover row cannot go out.
  const carried = (data?.groups ?? []).flatMap((group) => group.lines.filter(isCarried));

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

  /** A text field the estimator names by hand (FR-9): the part, a description, a NOTE. */
  function editText(line: QuoteLine, field: "part" | "description" | "substitutionNote", label: string) {
    const current = (line[field] as string | null | undefined) ?? "";
    const next = window.prompt(label, current);
    if (next === null || next.trim() === current || (field === "description" && !next.trim())) return;
    patchLine(line, { [field]: next.trim() || null });
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

  /** FR-14: move a line into a group, or mark a base line a substitution replaces. */
  async function regroup(line: QuoteLine, alternate: string | null, role?: "replaced") {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/alternates/assign`, {
        body: { ids: [line.id], alternate, scope: "quote-lines", ...(role ? { role } : {}) },
      });
      mutate();
      mutateAlternates();
    } catch (problem) {
      toast.error("Could not move that line", { description: errorMessage(problem) });
    }
  }

  /** FR-8: price the line at one of the rows it could as well be. */
  async function chooseMatch(line: QuoteLine, index: number) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/lines/${line.id}/close-matches/${index}`);
      toast.success("Close match chosen", { description: line.closeMatches?.[index]?.label ?? undefined });
      mutate();
    } catch (problem) {
      toast.error("Could not use that match", { description: errorMessage(problem) });
    }
  }

  /** NR-4: a list adder the legend names, added by the estimator - never by the ladder. */
  async function addAdder(line: QuoteLine, index: number) {
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/lines/${line.id}/adders/${index}`);
      toast.success("Adder added", { description: line.adderCandidates?.[index]?.name });
      mutate();
    } catch (problem) {
      toast.error("Could not add that adder", { description: errorMessage(problem) });
    }
  }

  async function keepCarried() {
    const from = carried[0]?.carriedFrom ?? "the prior bid";
    if (
      !window.confirm(
        `Keep the ${carried.length} line${carried.length === 1 ? "" : "s"} carried from ${from}? ` +
          "Remove any that do not apply to this job first.",
      )
    ) {
      return;
    }
    try {
      await proxyMutate(`/api/proxy/projects/${code}/quote/carried/keep`);
      toast.success("Carried lines kept");
      mutate();
    } catch (problem) {
      toast.error("Could not keep those lines", { description: errorMessage(problem) });
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

            {carried.length > 0 && (
              <button
                type="button"
                onClick={keepCarried}
                className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[12px] font-bold bg-status-warning-soft border border-status-warning/30 text-status-warning shadow-sm hover:brightness-110"
                title="Copied from a past bid. Remove what does not apply to this job, then keep the rest; the proposal waits until you do."
              >
                <ClockCounterClockwise size={14} weight="fill" />
                {carried.length} carried from {carried[0].carriedFrom ?? "a past bid"} · Keep
              </button>
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
            <button
              onClick={() => setCustomOpen(true)}
              title="A line past the stock list, described from the custom / other options"
              className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
            >
              <Plus size={14} weight="bold" />
              Custom line
            </button>
            <CustomLineDialog code={code} open={customOpen} onOpenChange={setCustomOpen} onAdded={() => mutate()} />
            <button
              onClick={() =>
                setCollapsed((current) =>
                  current.size ? new Set() : new Set(groups.map((group) => group.group)),
                )
              }
              className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
            >
              {collapsed.size ? (
                <ArrowsOutLineVertical size={14} weight="bold" />
              ) : (
                <ArrowsInLineVertical size={14} weight="bold" />
              )}
              {collapsed.size ? "Expand all" : "Collapse all"}
            </button>
          </div>

          {running && (
            <div className="anim-fadein relative overflow-hidden px-5 py-3 text-[13px] font-bold bg-status-warning-soft text-status-warning shadow-inner">
              <span className="anim-sweep" />
              Claude is matching and pricing the confirmed openings.
            </div>
          )}

          <div className="overflow-x-auto">
            <div style={{ minWidth: 1140 }}>
              <div
                className="grid gap-4 border-b border-subtle px-5 py-3 text-[11px] font-bold uppercase tracking-widest text-tx-muted bg-panel-muted"
                style={{ gridTemplateColumns: COLUMNS }}
              >
                <span>Component</span>
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
                groups.map((group) => {
                  const isOpening = group.group !== group.division;
                  const expanded = !collapsed.has(group.group);
                  // Slot order is a display rule, so it is applied here rather
                  // than asking the API to sort on something it does not store.
                  const lines = [...group.lines].sort(
                    (a, b) => slotRank(slotOf(a.description)) - slotRank(slotOf(b.description)),
                  );
                  return (
                  <div key={group.group}>
                    <div className="flex items-center gap-3 px-5 py-3.5 bg-panel-muted border-b border-subtle/50">
                      <button
                        type="button"
                        onClick={() => toggleGroup(group.group)}
                        aria-expanded={expanded}
                        aria-label={`${expanded ? "Collapse" : "Expand"} ${isOpening ? `opening ${group.group}` : group.division}`}
                        className="text-tx-muted transition-colors hover:text-tx-primary"
                      >
                        {expanded ? (
                          <CaretDown size={14} weight="bold" />
                        ) : (
                          <CaretRight size={14} weight="bold" />
                        )}
                      </button>
                      <span className="text-[14px] font-bold text-tx-primary tracking-tight">
                        {isOpening ? `Opening ${group.group}` : group.division}
                      </span>
                      <span className="text-[12px] font-medium text-tx-muted">
                        {isOpening ? `${group.division} · ` : ""}
                        {group.lines.length} component{group.lines.length === 1 ? "" : "s"}
                      </span>
                      <span className="flex-1" />
                      <span className="tnum text-[14px] font-bold text-brand-primary">
                        ${formatMoney(group.subtotal)}
                      </span>
                    </div>

                    {expanded && isOpening && (
                      <Nomenclature opening={group.group} division={group.division} />
                    )}

                    {expanded && lines.map((line) => (
                      <div
                        key={line.id}
                        className={`grid items-center gap-4 border-b border-subtle px-5 py-3.5 last:border-b-0 hover:bg-background/50 transition-colors ${line.addedByHand ? "border-l-4 border-l-status-error" : ""}`}
                        style={{ gridTemplateColumns: COLUMNS }}
                      >
                        <span
                          className={`truncate text-[11.5px] font-bold uppercase tracking-wider ${
                            slotOf(line.description) === "DOOR" ||
                            slotOf(line.description) === "FRAME"
                              ? "text-tx-primary"
                              : "text-tx-muted"
                          }`}
                        >
                          {slotOf(line.description)}
                        </span>

                        <button
                          type="button"
                          onClick={() => editText(line, "part", "Part number")}
                          aria-label={`Part number for ${line.description}`}
                          className="truncate text-left text-[13px] font-medium text-tx-secondary hover:text-tx-primary hover:underline"
                          title={line.part ?? "Name the part"}
                        >
                          {line.part ?? "—"}
                        </button>

                        <span className="min-w-0">
                          <span className="block truncate text-[13.5px] font-semibold text-tx-primary" title={line.description}>
                            {line.description}
                          </span>
                          {line.substitutionNote && (
                            <span className="mt-0.5 block text-[11.5px] font-medium text-brand-primary" title={line.substitutionNote}>
                              NOTE: {line.substitutionNote}
                            </span>
                          )}
                          <span className="mt-0.5 flex gap-2 text-[11px] font-semibold text-tx-muted">
                            <button type="button" className="hover:text-tx-primary hover:underline"
                              onClick={() => editText(line, "description", "Description")}>
                              Edit
                            </button>
                            <button type="button" className="hover:text-tx-primary hover:underline"
                              onClick={() => editText(line, "substitutionNote", "Substitution NOTE printed on the quote")}>
                              {line.substitutionNote ? "Edit NOTE" : "Add NOTE"}
                            </button>
                            {lineGroups.length > 0 && (
                              <select
                                aria-label={`Group for ${line.description}`}
                                value={line.alternateGroup ?? ""}
                                onChange={(event) => regroup(line, event.target.value || null)}
                                className="max-w-[140px] truncate rounded border border-subtle bg-background px-1 text-[11px] font-medium text-tx-secondary"
                              >
                                <option value="">Base bid</option>
                                {lineGroups.map((group) => (
                                  <option key={group.label} value={group.name ?? ""}>
                                    {group.label}
                                  </option>
                                ))}
                              </select>
                            )}
                            {!line.alternateGroup && substitutions.length > 0 && (
                              <select
                                aria-label={`Substitution replacing ${line.description}`}
                                value={line.deductedBy?.[0] ?? ""}
                                onChange={(event) => regroup(line, event.target.value || null, "replaced")}
                                className="max-w-[160px] truncate rounded border border-subtle bg-background px-1 text-[11px] font-medium text-tx-secondary"
                              >
                                <option value="">Not replaced</option>
                                {substitutions.map((group) => (
                                  <option key={group.label} value={group.name ?? ""}>
                                    Replaced in {group.label}
                                  </option>
                                ))}
                              </select>
                            )}
                          </span>
                          {!!line.closeMatches?.length && (
                            <details className="mt-1 text-[11.5px]">
                              <summary className="cursor-pointer font-semibold text-status-warning">
                                {line.closeMatches.length} close match{line.closeMatches.length === 1 ? "" : "es"}
                              </summary>
                              <ul className="mt-1 flex flex-col gap-1">
                                {line.closeMatches.map((match, index) => {
                                  const inUse = match.part === line.part && match.cost === line.cost;
                                  return (
                                    <li key={`${match.label}-${index}`} className="flex items-center gap-2">
                                      <span
                                        className="min-w-0 flex-1 truncate font-medium text-tx-secondary"
                                        title={match.costSourceDetail ?? undefined}
                                      >
                                        {match.label}
                                        {match.cost === null ? "" : ` · $${formatMoney(match.cost)}`}
                                      </span>
                                      <button
                                        type="button"
                                        disabled={inUse}
                                        onClick={() => chooseMatch(line, index)}
                                        className="shrink-0 rounded border border-subtle px-1.5 py-0.5 text-[11px] font-bold text-tx-secondary hover:text-tx-primary disabled:opacity-60"
                                      >
                                        {inUse ? "in use" : "Use"}
                                      </button>
                                    </li>
                                  );
                                })}
                              </ul>
                            </details>
                          )}
                          {!!line.adderCandidates?.length && (
                            <span className="mt-1 flex flex-wrap gap-1">
                              {line.adderCandidates.map((adder, index) => (
                                <button
                                  key={`${adder.name}-${index}`}
                                  type="button"
                                  onClick={() => addAdder(line, index)}
                                  title="The legend names this list adder. It goes on the list price, and the line's multiplier applies to the sum."
                                  className="rounded-md border border-status-warning/30 bg-status-warning-soft px-1.5 py-0.5 text-[10.5px] font-bold text-status-warning hover:brightness-110"
                                >
                                  + {adder.name} (list ${formatMoney(adder.listAdder)})
                                </button>
                              ))}
                            </span>
                          )}
                          {!!line.appliedAdders?.length && (
                            <span className="mt-0.5 block text-[11px] font-medium text-tx-muted">
                              with {line.appliedAdders.map((adder) => adder.name).join(", ")}
                            </span>
                          )}
                          {(line.marginOverridden || line.addedByHand) && (
                            <span className="text-[11.5px] font-medium text-status-error mt-0.5 block">
                              {line.addedByHand ? "added by hand" : "margin overridden"}
                              {line.overrideReason ? ` · ${line.overrideReason}` : ""}
                            </span>
                          )}
                          {line.marginOverridden && (
                            <select
                              aria-label={`Why the margin on ${line.description} is not the band's`}
                              value={line.overrideCode ?? ""}
                              onChange={(event) => event.target.value && patchLine(line, { overrideCode: event.target.value })}
                              className={`mt-0.5 rounded border px-1 text-[11px] font-medium ${
                                line.overrideCode
                                  ? "border-subtle bg-background text-tx-secondary"
                                  : "border-status-warning/40 bg-status-warning-soft text-status-warning"
                              }`}
                            >
                              <option value="" disabled>
                                Why? Choose a reason
                              </option>
                              {OVERRIDE_REASONS.map(([key, label]) => (
                                <option key={key} value={key}>
                                  {label}
                                </option>
                              ))}
                            </select>
                          )}
                          {line.stock === false && (
                            <span
                              className="inline-block mt-1 mr-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-tx-secondary border border-subtle bg-panel-muted shadow-sm"
                              title="Not on the maker's stock list (a draft until CBC confirms it, NR-6) - check the lead time"
                            >
                              non-stock
                            </span>
                          )}
                          {isCarried(line) && (
                            <span
                              className="inline-block mt-1 mr-1 rounded-md px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest text-status-warning border border-status-warning/30 bg-status-warning-soft shadow-sm"
                              title={`Copied from ${line.carriedFrom ?? "a past bid"}: keep it if it applies to this job, or remove it`}
                            >
                              carried
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
                            <span className="flex flex-col items-end gap-1">
                              <span
                                className="inline-flex items-center rounded-md px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-status-warning-soft text-status-warning border border-status-warning/30 shadow-xs whitespace-nowrap"
                                title={line.costSource === "DISTRIBUTOR_MANUAL" ? "Distributor manual quote — price may be out of date" : (line.priceStatus ?? line.costSource ?? "Manual")}
                              >
                                {formatCostSourceLabel(line.priceStatus ?? line.costSource)}
                              </span>
                              {line.costSource === "DISTRIBUTOR_MANUAL" && (
                                <span
                                  className="text-[9.5px] font-medium text-status-warning whitespace-nowrap"
                                  title="Price may be out of date — refresh"
                                >
                                  Price may be stale
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
                          onCommit={(next) => {
                            const margin = next === null ? null : Math.min(Math.max(next, 0), 99) / 100;
                            // Below band, the reason is what turns the review's
                            // blocking flag into a recorded decision - so it is
                            // asked for, never filled in. Otherwise none is sent.
                            if (!wouldBeBelowBand(line, margin)) {
                              patchLine(line, { margin });
                              return;
                            }
                            const reason = window
                              .prompt(`${formatPercent(margin ?? 0)} is below the band floor. Why?`)
                              ?.trim();
                            if (!reason) {
                              toast.error("Margin not changed", {
                                description: "A below-band margin needs a reason.",
                              });
                              return;
                            }
                            patchLine(line, { margin, overrideReason: reason });
                          }}
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
                          <select
                            aria-label={`Cost source for ${line.description}`}
                            value={line.costSource ?? "MANUAL"}
                            onChange={(event) => patchLine(line, { costSource: event.target.value })}
                            className="mt-0.5 w-full truncate rounded border border-subtle bg-background px-1 py-0.5 text-[11px] font-medium text-tx-secondary"
                          >
                            {[...new Set([...(line.costSource ? [line.costSource] : []), ...COST_SOURCES])].map((source) => (
                              <option key={source} value={source}>
                                {formatCostSourceLabel(source)}
                              </option>
                            ))}
                          </select>
                          {line.freshness && !line.lapsed && FRESHNESS[line.freshness.status] && (
                            <span
                              className={`inline-block mt-0.5 rounded-md border px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-widest shadow-sm ${FRESHNESS[line.freshness.status].tone}`}
                              title={`${line.freshness.basis}${line.freshness.asOf ? ` ${line.freshness.asOf}` : ""} — ${line.freshness.guidance}`}
                            >
                              {FRESHNESS[line.freshness.status].label}
                            </span>
                          )}
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
                  );
                })
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

        <VendorRfqsPanel
          code={code}
          lines={(data?.groups ?? []).flatMap((group) => group.lines)}
          onApplied={() => mutate()}
        />
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
