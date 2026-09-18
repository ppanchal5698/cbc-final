"use client";

import { useState } from "react";
import { Receipt } from "@phosphor-icons/react";
import { toast } from "sonner";

import { Input } from "@/components/ui/input";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";

/**
 * The P21 order raised against this bid.
 *
 * Closes the bid-to-order loop the dashboard reports on: a bid marked Won with
 * no order number is a sale nobody raised. It lives on the project, not the
 * proposal, because the board and the dashboard both read it.
 */
export function P21OrderField({
  code,
  value,
  onSaved,
}: {
  code: string;
  value: string;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState(value);
  const [busy, setBusy] = useState(false);
  const dirty = draft.trim() !== value.trim();

  async function save() {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${encodeURIComponent(code)}`, {
        method: "PATCH",
        body: { p21OrderNo: draft.trim() },
      });
      toast.success(draft.trim() ? `Linked to P21 order ${draft.trim()}` : "Order number cleared");
      onSaved();
    } catch (problem) {
      toast.error("Could not save the order number", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-subtle bg-panel p-5 shadow-1">
      <div className="flex items-center gap-2">
        <Receipt size={16} weight="duotone" className="text-brand-primary" />
        <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          P21 order
        </span>
      </div>

      <div className="mt-3 flex gap-2">
        <Input
          value={draft}
          placeholder="e.g. SO-44812"
          disabled={busy}
          aria-label="P21 order number"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="button"
          onClick={save}
          disabled={busy || !dirty}
          className="shrink-0 rounded-lg border border-subtle bg-background px-3 py-2 text-[12.5px] font-bold text-tx-secondary shadow-1 transition-colors hover:bg-panel-muted hover:text-tx-primary disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save"}
        </button>
      </div>

      <p className="mt-2 text-[11.5px] font-medium leading-relaxed text-tx-muted">
        {value
          ? `Linked to P21 order ${value}. The bid and the order now report together.`
          : "Once purchasing raises the order in P21, drop the number here to close the bid-to-order loop."}
      </p>
    </div>
  );
}
