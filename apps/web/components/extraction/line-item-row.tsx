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
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/status-badge";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { LineItem, LineStatus } from "@/lib/types";

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
] as const;

const FLAG_HINTS: Record<string, string> = {
  fire_rating_missing: "Missing — flag only (Matrix 7.3 pending)",
  handing_missing: "Missing handing",
  finish_missing: "Missing finish",
  finish_ambiguous: "Ambiguous finish code — confirm which satin",
  finish_unrecognized: "Finish not in CBC crosswalk",
};

export function LineItemRow({
  item,
  code,
  selected,
  focused = false,
  picked = false,
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

            {item.status === "duplicate" && (
              <div className="mt-4 flex items-center gap-3 rounded-xl px-4 py-3.5 bg-status-error-soft border border-status-error/30 shadow-sm">
                <Copy size={18} weight="fill" className="text-status-error" />
                <span className="flex-1 text-[13px] font-medium text-status-error leading-relaxed">
                  {item.duplicateReason ?? "This line was read from more than one document."}
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
