"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { PencilSimple } from "@phosphor-icons/react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { Project } from "@/lib/types";

const FIELDS = [
  { key: "name", label: "Job name", type: "text" },
  { key: "brand", label: "Brand", type: "text" },
  { key: "location", label: "Location", type: "text" },
  { key: "state", label: "State", type: "text" },
  { key: "gc", label: "General contractor", type: "text" },
  { key: "initiator", label: "Requested by", type: "text" },
  { key: "architect", label: "Architect", type: "text" },
  { key: "projectNumber", label: "Project number", type: "text" },
  { key: "bidDue", label: "Bid due", type: "date" },
] as const;

type FieldKey = (typeof FIELDS)[number]["key"];

function valuesOf(project: Project): Record<FieldKey, string> {
  return Object.fromEntries(
    FIELDS.map(({ key }) => [
      key,
      key === "bidDue" ? (project.bidDue ?? "").slice(0, 10) : String(project[key] ?? ""),
    ]),
  ) as Record<FieldKey, string>;
}

/** Correct a bid's header details after intake - PATCH /api/projects/{code}. */
export function EditBidButton({ project }: { project: Project }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState(() => valuesOf(project));

  function begin() {
    setValues(valuesOf(project));
    setOpen(true);
  }

  async function save() {
    if (!values.name.trim()) {
      toast.error("Job name is required");
      return;
    }
    // The API ignores null fields, so a blank one cannot clear a value - send only
    // what was actually changed to something.
    const before = valuesOf(project);
    const changed: Record<string, string> = {};
    for (const { key } of FIELDS) {
      const value = key === "state" ? values[key].trim().toUpperCase() : values[key].trim();
      if (value && value !== before[key]) changed[key] = value;
    }
    if (Object.keys(changed).length === 0) {
      setOpen(false);
      return;
    }
    if (changed.state && changed.state.length !== 2) {
      toast.error("Use a two-letter state code (e.g. OH)");
      return;
    }

    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${encodeURIComponent(project.code)}`, {
        method: "PATCH",
        body: changed,
      });
      toast.success(`${project.code} updated`);
      setOpen(false);
      router.refresh();
    } catch (problem) {
      toast.error("Could not update the bid", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="border-t border-subtle px-5 py-4 bg-background">
        <button
          type="button"
          onClick={begin}
          className="flex w-full items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-[13px] font-bold border border-subtle text-tx-secondary bg-panel hover:bg-panel-muted transition-colors shadow-sm"
        >
          <PencilSimple size={16} weight="bold" />
          Edit bid details
        </button>
      </div>

      <Dialog open={open} onOpenChange={(next) => !busy && setOpen(next)}>
        <DialogContent showCloseButton={!busy}>
          <DialogHeader>
            <DialogTitle>Edit bid details</DialogTitle>
            <DialogDescription>
              Correct what intake recorded for <strong>{project.code}</strong>. Only fields you
              change are saved; a blank field keeps its current value.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            {FIELDS.map((field) => (
              <label
                key={field.key}
                className={field.key === "name" ? "flex flex-col gap-1.5 sm:col-span-2" : "flex flex-col gap-1.5"}
              >
                <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                  {field.label}
                </span>
                <Input
                  type={field.type}
                  value={values[field.key]}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field.key]: event.target.value }))
                  }
                  disabled={busy}
                />
              </label>
            ))}
          </div>
          <DialogFooter>
            <button
              type="button"
              onClick={() => setOpen(false)}
              disabled={busy}
              className="rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={save}
              disabled={busy}
              className="rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 bg-brand-primary text-white hover:bg-brand-primary/90 transition-colors shadow-sm"
            >
              {busy ? "Saving…" : "Save changes"}
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
