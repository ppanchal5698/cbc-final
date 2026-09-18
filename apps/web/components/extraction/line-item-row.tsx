"use client";

import { useState } from "react";
import {
  CheckCircle,
  Copy,
  WarningCircle,
  PencilSimple,
  Trash,
  FloppyDisk,
  Eye,
  Warning,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/status-badge";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { LineItem, LineStatus, ReviewFlag } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS: Record<
  LineStatus,
  { label: string; colourClass: string; softClass: string; lineClass: string; Icon: typeof CheckCircle }
> = {
  clear: {
    label: "Clear",
    colourClass: "text-brand-primary",
    softClass: "bg-brand-primary/10",
    lineClass: "border-brand-primary/20",
    Icon: CheckCircle,
  },
  needs_look: {
    label: "Looks right",
    colourClass: "text-status-warning",
    softClass: "bg-status-warning-soft",
    lineClass: "border-status-warning/30",
    Icon: WarningCircle,
  },
  duplicate: {
    label: "Keep one",
    colourClass: "text-status-error",
    softClass: "bg-status-error-soft",
    lineClass: "border-status-error/30",
    Icon: Copy,
  },
  by_hand: {
    label: "By hand",
    colourClass: "text-status-success",
    softClass: "bg-status-success-soft",
    lineClass: "border-status-success/30",
    Icon: PencilSimple,
  },
};

/** Must match the header in ExtractionClient, hence the shared constant. */
export const ROW_COLUMNS = "28px 34px 60px minmax(160px,1fr) 110px 60px 100px 120px";

const EDITABLE = [
  { key: "mark", label: "Mark", width: "80px" },
  { key: "description", label: "Description", width: "1fr" },
  { key: "size", label: "Size", width: "110px" },
  { key: "qty", label: "Qty", width: "70px" },
  { key: "division", label: "Division", width: "110px" },
  { key: "hwSet", label: "HW set", width: "110px" },
] as const;

/** FR-2 attributes — editable in the expanded panel so estimators can correct before pricing. */
const ATTRIBUTE_FIELDS = [
  { key: "handing", label: "Handing", missingFlag: "handing_missing", placeholder: "LH / RH / LHR / RHR" },
  { key: "finish", label: "Finish", missingFlag: "finish_missing", placeholder: "US26D or 626" },
  {
    key: "fireRating",
    label: "Fire rating",
    missingFlag: "fire_rating_missing",
    placeholder: "20 / 45 / 60 / 90",
  },
  { key: "frameDepth", label: "Frame depth", missingFlag: null, placeholder: "5-5/8\" … CUSTOM" },
  // Both were carried all the way into Mongo and then shown nowhere: frameType
  // was rendered by no component at all, and wallType was printed in the summary
  // line but could not be corrected - even though frameDepth is derived from it.
  { key: "frameType", label: "Frame type", missingFlag: null, placeholder: "HM / KD / welded" },
  { key: "wallType", label: "Wall type", missingFlag: "wall_type_missing", placeholder: "drywall / masonry / 2x4" },
] as const;

const FLAG_HINTS: Record<string, string> = {
  fire_rating_missing:
    "Mandatory fire rating — searched schedule / type schedule / Div 08 on the PDF; still absent or uncertain",
  handing_missing:
    "Agent searched schedule + floor-plan swing on the PDF — still unresolved",
  finish_missing: "Required finish — checked HW group / sheet note on the PDF; still absent",
  finish_ambiguous: "Ambiguous finish code — confirm which satin",
  finish_unrecognized: "Finish not in CBC crosswalk — confirm on sheet",
  keying_missing: "Lock/IC hardware implies keying options — fill the keying block",
  frame_depth_needs_wall_assembly_review: "Wall type needed before throat depth",
  hardware_set_missing: "No GROUP / HW set on the schedule row",
  hardware_matrix_unexpanded: "Matrix X columns — expand hardware from legend",
  out_of_scope_storefront: "Aluminum / storefront — not a CBC HM/WD quote line",
  wall_type_missing: "Missing wall type",
  frame_depth_underivable: "Frame depth needs wall type",
  details_dropped: "Schedule cells (glass / materials / notes) were not carried into fields",
};

const MATERIAL_FIELDS = [
  { key: "doorType", label: "Door type" },
  { key: "doorMaterial", label: "Door material" },
  { key: "frameMaterial", label: "Frame material" },
  { key: "glass", label: "Glass" },
  { key: "manufacturer", label: "Manufacturer" },
  { key: "series", label: "Series" },
  { key: "location", label: "Location" },
] as const;

const KEYING_CORE_OPTIONS = [
  { value: "", label: "—" },
  { value: "icSmallFormat", label: "IC small format" },
  { value: "icLargeFormat", label: "IC large format" },
  { value: "conventional", label: "Conventional" },
  { value: "none", label: "None" },
] as const;

export function LineItemRow({
  item,
  code,
  selected,
  focused = false,
  picked = false,
  twin = null,
  reviewFlags = [],
  onPick,
  onSelect,
  onChanged,
}: {
  item: LineItem;
  code: string;
  selected: boolean;
  /** The keyboard cursor is on this row. */
  focused?: boolean;
  /** Ticked for a bulk action. */
  picked?: boolean;
  /** The other reading of a duplicate, so Keep one / Keep both is an informed choice. */
  twin?: LineItem | null;
  /** This opening's review flags, so the weak fields are named on the row. */
  reviewFlags?: ReviewFlag[];
  onPick?: () => void;
  onSelect: (item: LineItem | null) => void;
  onChanged: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState<{ from: string; values: Record<string, string> } | null>(
    null,
  );

  const status = STATUS[item.status];
  const evidence = item.evidence;
  const flags = item.flags ?? [];

  // Identity of the server's version of this row. The draft used to be seeded
  // once and never re-synced, so a re-run that changed a line while the screen
  // was open left the form showing the old values - and "Save my changes" wrote
  // them straight back over what Claude had just read.
  const revision = [
    item.mark,
    item.description,
    item.size,
    item.qty,
    item.division,
    item.hwSet,
    item.handing,
    item.finish,
    item.fireRating,
    item.frameDepth,
    item.frameType,
    item.wallType,
    item.doorType,
    item.doorMaterial,
    item.frameMaterial,
    item.glass,
    item.manufacturer,
    item.series,
    item.location,
    item.hardware,
    item.notes,
    JSON.stringify(item.keying ?? null),
    item.confirmedAt,
  ].join("\u0000");

  const draft =
    edits?.from === revision
      ? edits.values
      : {
          mark: item.mark ?? "",
          description: item.description ?? "",
          size: item.size ?? "",
          qty: String(item.qty ?? 1),
          division: item.division ?? "",
          hwSet: item.hwSet ?? "",
          handing: item.handing ?? "",
          finish: item.finish ?? "",
          fireRating: item.fireRating ?? "",
          frameDepth: item.frameDepth ?? "",
          frameType: item.frameType ?? "",
          wallType: item.wallType ?? "",
          doorType: item.doorType ?? "",
          doorMaterial: item.doorMaterial ?? "",
          frameMaterial: item.frameMaterial ?? "",
          glass: item.glass ?? "",
          manufacturer: item.manufacturer ?? "",
          series: item.series ?? "",
          location: item.location ?? "",
          hardware: item.hardware ?? "",
          notes: item.notes ?? "",
          keyingCoreType: item.keying?.coreType ?? "",
          keyingKeyway: item.keying?.keyway ?? "",
          keyingLockFunction: item.keying?.lockFunction ?? "",
          keyingNotes: item.keying?.notes ?? "",
        };

  const dirty = edits?.from === revision;

  function setField(key: string, value: string) {
    setEdits({ from: revision, values: { ...draft, [key]: value } });
  }

  async function call(
    path: string,
    init: Parameters<typeof proxyMutate>[1],
    success: string,
  ): Promise<boolean> {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}/line-items${path}`, init);
      toast.success(success);
      setEdits(null);
      onChanged();
      return true;
    } catch (problem) {
      toast.error("That did not go through", { description: errorMessage(problem) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  const confirm = () =>
    call(`/${item.id}/confirm`, { method: "POST" }, `${item.mark ?? "Line"} kept as is`);

  const save = () => {
    const qty = Number(draft.qty);
    if (draft.qty.trim() === "" || Number.isNaN(qty) || qty <= 0) {
      toast.error("Quantity has to be a positive number", {
        description: `"${draft.qty}" is not one, so nothing was saved.`,
      });
      return Promise.resolve(false);
    }
    if (!draft.description.trim()) {
      toast.error("A line needs a description");
      return Promise.resolve(false);
    }
    return call(
      `/${item.id}`,
      {
        method: "PATCH",
        body: {
          mark: draft.mark || null,
          description: draft.description.trim(),
          size: draft.size || null,
          qty,
          division: draft.division || null,
          hwSet: draft.hwSet || null,
          handing: draft.handing || null,
          finish: draft.finish || null,
          fireRating: draft.fireRating || null,
          frameDepth: draft.frameDepth || null,
          frameType: draft.frameType || null,
          wallType: draft.wallType || null,
          doorType: draft.doorType || null,
          doorMaterial: draft.doorMaterial || null,
          frameMaterial: draft.frameMaterial || null,
          glass: draft.glass || null,
          manufacturer: draft.manufacturer || null,
          series: draft.series || null,
          location: draft.location || null,
          hardware: draft.hardware || null,
          notes: draft.notes || null,
          keying:
            draft.keyingCoreType ||
            draft.keyingKeyway ||
            draft.keyingLockFunction ||
            draft.keyingNotes
              ? {
                  coreType: draft.keyingCoreType || null,
                  keyway: draft.keyingKeyway || null,
                  lockFunction: draft.keyingLockFunction || null,
                  notes: draft.keyingNotes || null,
                }
              : null,
        },
      },
      "Your changes are saved",
    );
  };

  const remove = () => {
    if (!window.confirm(`Remove ${item.mark ?? "this line"} — "${item.description}"?`)) {
      return Promise.resolve(false);
    }
    return call(`/${item.id}`, { method: "DELETE" }, `${item.mark ?? "Line"} removed`);
  };

  const resolveDuplicate = (keep: "one" | "both") =>
    call(
      `/${item.id}/resolve-duplicate`,
      { method: "POST", body: { keep } },
      keep === "one" ? "Kept one reading" : "Kept both as separate lines",
    );

  function toggleOpen() {
    const next = !open;
    setOpen(next);
    onSelect(next ? item : null);
  }

  function flagFor(field: (typeof ATTRIBUTE_FIELDS)[number]): string | null {
    if (field.missingFlag && flags.includes(field.missingFlag)) return field.missingFlag;
    if (field.key === "finish") {
      if (flags.includes("finish_ambiguous")) return "finish_ambiguous";
      if (flags.includes("finish_unrecognized")) return "finish_unrecognized";
    }
    return null;
  }

  return (
    <div
      data-row-id={item.id}
      className={`border-b border-subtle transition-colors ${
        picked ? "bg-brand-primary/10" : selected ? "bg-panel-muted" : "bg-transparent"
      }`}
      style={{
        boxShadow: focused ? "inset 4px 0 0 var(--color-brand-primary)" : undefined,
      }}
    >
      <div
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-label={`${item.mark ? `${item.mark}: ` : ""}${item.description}`}
        className="grid cursor-pointer items-center gap-3 px-5 py-3 hover:bg-background/30 transition-colors"
        style={{ gridTemplateColumns: ROW_COLUMNS }}
        onClick={toggleOpen}
      >
        <span onClick={(event) => event.stopPropagation()}>
          <input
            type="checkbox"
            aria-label={`Select ${item.mark ?? item.description}`}
            checked={picked}
            onChange={() => onPick?.()}
          />
        </span>

        <span className={`grid h-7 w-7 place-items-center rounded-lg shadow-sm border ${status.softClass} ${status.colourClass} ${status.lineClass}`}>
          <status.Icon size={16} weight="duotone" />
        </span>

        <span className="tnum text-[13.5px] font-bold text-tx-primary">{item.mark ?? "—"}</span>

        <span className="min-w-0 flex flex-col justify-center">
          <span className="block truncate text-[13px] font-medium text-tx-secondary">{item.description}</span>
          {flags.length > 0 && (
            <span className="mt-1 flex flex-wrap gap-1.5">
              {flags.slice(0, 3).map((flag) => (
                <StatusBadge key={flag} variant="caution" dashed>
                  {flag.replace(/_/g, " ")}
                </StatusBadge>
              ))}
            </span>
          )}
        </span>

        <span className="tnum text-[12.5px] font-medium text-tx-muted">
          {item.size ?? "—"}
        </span>
        <span className="tnum text-[12.5px] font-medium text-tx-muted">
          {item.qty}
        </span>
        <span className="text-[12.5px] font-medium text-tx-muted">
          {item.hwSet ?? "—"}
        </span>

        <span className="flex justify-end">
          <span className={`rounded-lg px-3 py-1 text-[11px] font-bold uppercase tracking-widest border shadow-sm ${status.softClass} ${status.colourClass} ${status.lineClass}`}>
            {status.label}
          </span>
        </span>
      </div>

      {open && (
        <div className="anim-fadein px-5 pb-5">
          <div className="rounded-xl p-5 bg-panel border border-subtle shadow-sm">
            <div className="flex items-start gap-3.5">
              <status.Icon size={20} weight="fill" className={status.colourClass} />
              <div className="min-w-0 flex-1">
                <span className="block text-[14px] font-bold text-tx-primary tracking-tight">
                  {item.addedByHand
                    ? "Added by hand"
                    : item.status === "duplicate"
                      ? "Read twice"
                      : item.confidence && item.confidence >= 0.75
                        ? "Read cleanly from the sheet"
                        : "Worth a second look"}
                </span>
                <span className="mt-1 block text-[13px] font-medium text-tx-secondary leading-relaxed">
                  {evidence?.note ??
                    (item.addedByHand
                      ? "Typed in by an estimator, so there is nothing to check it against."
                      : "Read from the door schedule.")}
                </span>
                <span className="mt-2 block text-[11.5px] font-bold uppercase tracking-widest text-tx-muted">
                  {evidence?.sourcePage ? `page ${evidence.sourcePage}` : "no source page"}
                  {evidence?.row ? ` · row ${evidence.row}` : ""}
                  {item.confidence !== null && item.confidence !== undefined
                    ? ` · ${Math.round(item.confidence * 100)}% confidence`
                    : ""}
                  {item.alternateGroup ? ` · alternate ${item.alternateGroup}` : ""}
                  {item.wallType ? ` · wall ${item.wallType}` : ""}
                  {!evidence?.bbox && !item.addedByHand && " · no position recorded"}
                </span>
              </div>

              {evidence?.sourcePage && (
                <button
                  onClick={(event) => {
                    event.stopPropagation();
                    onSelect(item);
                  }}
                  className="flex shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-[12px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
                >
                  <Eye size={16} weight="bold" />
                  See it on the sheet
                </button>
              )}
            </div>

            {item.rawRow && (
              <div className="mt-4 rounded-xl border border-subtle bg-panel-muted px-4 py-3">
                <span className="block text-[11.5px] font-bold uppercase tracking-widest text-tx-muted">
                  What the sheet printed
                </span>
                <code className="mt-1.5 block break-words font-mono text-[12px] leading-relaxed text-tx-secondary">
                  {item.rawRow}
                </code>
                {(item.width || item.height) && (
                  <span className="mt-1.5 block text-[11.5px] font-medium text-tx-muted">
                    {item.width ?? "?"} &times; {item.height ?? "?"}
                    {item.sizeNotation ? ` · read as ${item.sizeNotation}` : ""}
                  </span>
                )}
              </div>
            )}

            {item.inScope === false && (
              <div className="mt-4 rounded-xl border border-status-warning/30 bg-status-warning-soft px-4 py-3">
                <span className="block text-[11.5px] font-bold uppercase tracking-widest text-status-warning">
                  Not quoted{item.scopeRule ? ` · ${item.scopeRule.replace(/_/g, " ")}` : ""}
                </span>
                <span className="mt-1 block text-[13px] font-medium text-tx-secondary leading-relaxed">
                  {item.scopeReason ?? "Out of CBC's estimating scope."}
                </span>
              </div>
            )}

            {item.inScope === null && !item.addedByHand && (
              <div className="mt-4 rounded-xl border border-subtle bg-panel-muted px-4 py-3">
                <span className="block text-[11.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Scope not decided
                </span>
                <span className="mt-1 block text-[13px] font-medium text-tx-secondary leading-relaxed">
                  {item.scopeReason ?? "The rules do not cover this row - your call."}
                </span>
              </div>
            )}

            {item.status === "duplicate" && (
              <div className="mt-4 flex flex-wrap items-center gap-3 rounded-xl px-4 py-3.5 bg-status-error-soft border border-status-error/30 shadow-sm">
                <Copy size={18} weight="fill" className="text-status-error" />
                <span className="flex-1 min-w-[220px] text-[13px] font-medium text-status-error leading-relaxed">
                  {item.duplicateReason ?? "This line was read from more than one document."}
                  {/* Keep one drops a reading, so say which one is on the other side. */}
                  {twin && (
                    <span className="mt-1 block text-[12px] font-medium text-tx-secondary">
                      The other reading:{" "}
                      {twin.evidence?.sourcePage ? `page ${twin.evidence.sourcePage}` : "no page recorded"}
                      {twin.evidence?.row ? ` · row ${twin.evidence.row}` : ""} · {twin.qty} ×{" "}
                      {twin.description}
                    </span>
                  )}
                </span>
                <button
                  onClick={() => resolveDuplicate("one")}
                  disabled={busy}
                  className="rounded-lg px-4 py-2 text-[12px] font-bold bg-status-error text-white hover:bg-status-error/90 transition-colors shadow-sm"
                >
                  Keep one
                </button>
                <button
                  onClick={() => resolveDuplicate("both")}
                  disabled={busy}
                  className="rounded-lg px-4 py-2 text-[12px] font-bold border border-status-error/30 text-status-error bg-background hover:bg-status-error/10 transition-colors shadow-sm"
                >
                  Keep both
                </button>
              </div>
            )}

            {reviewFlags.length > 0 && (
              <div className="mt-4 rounded-xl border border-subtle bg-panel-muted px-4 py-3">
                <span className="block text-[11.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Fields to check on this opening
                </span>
                {/* Extraction records one confidence for the row, not one per
                    field, so this names the fields the reviewer actually
                    flagged rather than inventing a number for each. */}
                <ul className="mt-2 flex flex-wrap gap-1.5">
                  {reviewFlags.map((flag, index) => (
                    <li
                      key={`${flag.field}-${index}`}
                      title={flag.note ?? flag.issue ?? undefined}
                      className={cn(
                        "flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11.5px] font-semibold",
                        flag.severity === "high" || flag.severity === "critical"
                          ? "border-status-error/30 bg-status-error-soft text-status-error"
                          : flag.severity === "medium"
                            ? "border-status-warning/30 bg-status-warning-soft text-status-warning"
                            : "border-subtle bg-panel text-tx-secondary",
                      )}
                    >
                      <Warning size={12} weight="duotone" />
                      {(flag.field ?? "review").replaceAll("_", " ")}
                    </li>
                  ))}
                </ul>
                <span className="mt-2 block text-[12px] font-medium leading-relaxed text-tx-secondary">
                  {reviewFlags[0].note ?? reviewFlags[0].issue ?? reviewFlags[0].action_required}
                </span>
              </div>
            )}

            <div
              className="mt-5 grid gap-3 sm:grid-cols-2 lg:[grid-template-columns:var(--editable-cols)]"
              style={
                {
                  "--editable-cols": EDITABLE.map((f) => f.width).join(" "),
                } as React.CSSProperties
              }
            >
              {EDITABLE.map((field) => (
                <label key={field.key} className="block">
                  <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-1.5">
                    {field.label}
                  </span>
                  <input
                    value={draft[field.key] ?? ""}
                    inputMode={field.key === "qty" ? "numeric" : undefined}
                    onChange={(event) => setField(field.key, event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
              ))}
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {ATTRIBUTE_FIELDS.map((field) => {
                const hintFlag = flagFor(field);
                return (
                  <label key={field.key} className="block">
                    <span className="mb-1.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                      {field.label}
                      {hintFlag && (
                        <StatusBadge variant="caution" dashed>
                          {FLAG_HINTS[hintFlag] ?? hintFlag.replace(/_/g, " ")}
                        </StatusBadge>
                      )}
                    </span>
                    <input
                      value={draft[field.key] ?? ""}
                      placeholder={field.placeholder}
                      onChange={(event) => setField(field.key, event.target.value)}
                      className={`w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm ${
                        hintFlag ? "border-status-warning/40" : "border-subtle"
                      }`}
                    />
                  </label>
                );
              })}
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {MATERIAL_FIELDS.map((field) => (
                <label key={field.key} className="block">
                  <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    {field.label}
                  </span>
                  <input
                    value={draft[field.key] ?? ""}
                    onChange={(event) => setField(field.key, event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
              ))}
            </div>

            <div className="mt-4">
              <span className="mb-1.5 flex items-center gap-2 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Keying
                {flags.includes("keying_missing") && (
                  <StatusBadge variant="caution" dashed>
                    {FLAG_HINTS.keying_missing}
                  </StatusBadge>
                )}
              </span>
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium text-tx-muted">Core type</span>
                  <select
                    value={draft.keyingCoreType ?? ""}
                    onChange={(event) => setField("keyingCoreType", event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  >
                    {KEYING_CORE_OPTIONS.map((opt) => (
                      <option key={opt.value || "empty"} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium text-tx-muted">Keyway</span>
                  <input
                    value={draft.keyingKeyway ?? ""}
                    placeholder="e.g. Schlage C"
                    onChange={(event) => setField("keyingKeyway", event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium text-tx-muted">Lock function</span>
                  <input
                    value={draft.keyingLockFunction ?? ""}
                    placeholder="e.g. storeroom"
                    onChange={(event) => setField("keyingLockFunction", event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-medium text-tx-muted">Keying notes</span>
                  <input
                    value={draft.keyingNotes ?? ""}
                    onChange={(event) => setField("keyingNotes", event.target.value)}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
              </div>
            </div>

            {(draft.hardware || draft.notes) && (
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    Hardware
                  </span>
                  <textarea
                    value={draft.hardware ?? ""}
                    onChange={(event) => setField("hardware", event.target.value)}
                    rows={2}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
                <label className="block">
                  <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    Notes
                  </span>
                  <textarea
                    value={draft.notes ?? ""}
                    onChange={(event) => setField("notes", event.target.value)}
                    rows={2}
                    className="w-full rounded-lg px-3 py-2 text-[13px] font-medium outline-none transition-all bg-panel-muted border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30 shadow-sm"
                  />
                </label>
              </div>
            )}

            <div className="mt-6 flex items-center gap-3 border-t border-subtle pt-4">
              <button
                onClick={confirm}
                disabled={busy}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 transition-colors bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
              >
                <CheckCircle size={16} weight="bold" />
                Keep as is
              </button>
              <button
                onClick={save}
                disabled={busy || !dirty}
                title={dirty ? undefined : "Nothing changed yet"}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 transition-colors border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary shadow-sm"
              >
                <FloppyDisk size={16} weight="bold" />
                Save my changes
              </button>
              <span className="flex-1" />
              <button
                onClick={remove}
                disabled={busy}
                className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 transition-colors text-status-error hover:bg-status-error-soft hover:text-status-error"
              >
                <Trash size={16} weight="fill" />
                Remove
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
