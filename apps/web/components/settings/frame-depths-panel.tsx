"use client";

import { useState } from "react";
import useSWR from "swr";
import { Ruler, Plus, Trash } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { FrameDepths } from "@/lib/types";

const DEPTHS_URL = "/api/proxy/reference/frame-depths";

/**
 * Edit frame throat depths by wall type (Matrix 7.0). Read by the take-off pass
 * to derive a frame depth. `depth` is a label like 5-3/4; the API derives the
 * inches. Writes reference-library/frame_depths/wall_type_to_depth.json.
 */
export function FrameDepthsPanel() {
  const { data, error, isLoading, mutate } = useSWR<FrameDepths>(DEPTHS_URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ type: "", depth: "" });

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate<FrameDepths>(DEPTHS_URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save that depth", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function commitDepth(type: string, raw: string, current: string) {
    const next = raw.trim();
    if (next === current.trim()) return;
    if (!next) {
      toast.error("Depth cannot be blank", { description: "e.g. 5-3/4 or 5.75." });
      mutate();
      return;
    }
    save({ wall_types: [{ type, depth: next }] }, `${type} set to ${next}"`);
  }

  function commitNote(type: string, raw: string, current: string) {
    if (raw.trim() === current.trim()) return;
    save({ wall_types: [{ type, note: raw.trim() || null }] }, `${type} note updated`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const type = draft.type.trim();
    const depth = draft.depth.trim();
    if (!type) {
      toast.error("Give the wall type a name");
      return;
    }
    if (!depth) {
      toast.error("Enter a depth", { description: "e.g. 5-3/4 or 5.75." });
      return;
    }
    save({ wall_types: [{ type, depth }] }, `${type} added`);
    setDraft({ type: "", depth: "" });
  }

  function remove(type: string) {
    if (!window.confirm(`Remove the "${type}" wall type?`)) return;
    save({ remove: [type] }, `${type} removed`);
  }

  const inputClass = "rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";
  const wallTypes = data?.wall_types ?? [];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Ruler size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Frame depths by wall type</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Throat depth the take-off derives from wall construction. Enter as 5-3/4 or 5.75.
          Administrators only.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the frame depths: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">
          Loading…
        </p>
      )}

      {data && (
        <div className="divide-y divide-subtle flex-1 overflow-y-auto">
          {wallTypes.map((wall) => (
            <div key={wall.type} className="px-5 py-4 hover:bg-panel-muted transition-colors">
              <div className="flex items-center gap-4">
                <span className="min-w-0 flex-1 truncate text-[14px] font-semibold capitalize text-tx-primary">
                  {wall.type}
                </span>
                <span className="tnum shrink-0 text-[12.5px] font-medium text-tx-muted w-[56px] text-right">
                  {wall.depth_inches}&quot;
                </span>
                <input
                  key={`${wall.type}-${wall.depth}`}
                  defaultValue={wall.depth}
                  disabled={busy}
                  aria-label={`${wall.type} depth`}
                  onBlur={(event) => commitDepth(wall.type, event.target.value, wall.depth)}
                  className={`tnum w-24 shrink-0 text-right ${inputClass}`}
                />
                <button
                  type="button"
                  onClick={() => remove(wall.type)}
                  disabled={busy}
                  aria-label={`Remove ${wall.type}`}
                  className="shrink-0 rounded-md p-2 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors focus:ring-2 focus:ring-status-error"
                >
                  <Trash size={16} />
                </button>
              </div>
              <input
                key={`${wall.type}-note-${wall.note ?? ""}`}
                defaultValue={wall.note ?? ""}
                disabled={busy}
                placeholder="note (optional)"
                aria-label={`${wall.type} note`}
                onBlur={(event) => commitNote(wall.type, event.target.value, wall.note ?? "")}
                className={`mt-3 w-full !text-[12.5px] ${inputClass} !text-tx-secondary`}
              />
            </div>
          ))}
        </div>
      )}

      {data && (
        <form
          onSubmit={add}
          className="flex items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4"
        >
          <input
            value={draft.type}
            onChange={(event) => setDraft((d) => ({ ...d, type: event.target.value }))}
            placeholder="Wall type, e.g. masonry"
            aria-label="New wall type"
            className={`min-w-0 flex-1 ${inputClass}`}
          />
          <input
            value={draft.depth}
            onChange={(event) => setDraft((d) => ({ ...d, depth: event.target.value }))}
            placeholder="5-3/4"
            aria-label="New wall type depth"
            className={`tnum w-24 text-right ${inputClass}`}
          />
          <button
            type="submit"
            disabled={busy}
            className="flex items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50 h-[38px]"
          >
            <Plus size={16} weight="bold" />
            Add
          </button>
        </form>
      )}

      {data?.unknown_wall_type_rule && (
        <p className="border-t border-subtle bg-panel-muted px-5 py-3 text-[11.5px] font-medium text-tx-muted rounded-b-xl">
          {data.unknown_wall_type_rule}
          {data.adjustable_frames ? " Adjustable frames are a valid answer when the wall type is unclear." : ""}
        </p>
      )}
    </section>
  );
}
