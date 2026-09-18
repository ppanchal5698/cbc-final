"use client";

import { useState } from "react";
import useSWR from "swr";
import { Prohibit, PaperPlaneTilt, Trophy, ArrowBendDownLeft, Minus } from "@phosphor-icons/react";
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
import { patchBid } from "@/components/bids/bid-state";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { BidStatus, EnteredByRole, Outcome, Person, Project } from "@/lib/types";
import { cn } from "@/lib/utils";

const ROLES: EnteredByRole[] = ["Sales", "Estimating", "Purchasing", "Operations"];

/** Chip row. Everything in this dialog is a choice from a short, closed list. */
function Chips<T extends string>({
  options,
  value,
  onPick,
  disabled,
}: {
  options: { value: T; label: string; icon?: React.ReactNode }[];
  value: T;
  onPick: (value: T) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const on = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            disabled={disabled}
            onClick={() => onPick(option.value)}
            className={cn(
              "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12.5px] font-semibold transition-colors disabled:opacity-40",
              on
                ? "border-tx-primary bg-tx-primary text-background"
                : "border-subtle bg-transparent text-tx-secondary hover:bg-panel-muted",
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">{label}</span>
      {children}
    </label>
  );
}

/**
 * Who owns a bid and how it ended.
 *
 * Separate from the intake "Edit bid details" dialog on purpose: that one
 * corrects what intake read off the PDF, this one records what the desk
 * decided. Date entered is shown but not editable - it is the envelope's
 * createdAt, not a field anyone should be able to rewrite.
 */
export function BidStateDialog({
  project,
  open,
  onOpenChange,
  onSaved,
}: {
  project: Project | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState<{
    initiator: string;
    enteredByRole: EnteredByRole | "";
    bidDue: string;
    assignedEstimator: string;
    bidStatus: BidStatus;
    outcome: Outcome;
    p21OrderNo: string;
  } | null>(null);

  const { data } = useSWR<{ users: Person[] }>(
    open ? "/api/proxy/users/directory" : null,
    proxyFetcher,
  );

  // Seed the draft the first time the dialog opens on a given bid.
  if (open && project && draft === null) {
    setDraft({
      initiator: project.initiator ?? "",
      enteredByRole: project.enteredByRole ?? "",
      bidDue: (project.bidDue ?? "").slice(0, 10),
      assignedEstimator: project.assignedEstimator ?? "",
      bidStatus: project.bidStatus ?? "bid",
      outcome: project.outcome ?? "",
      p21OrderNo: project.p21OrderNo ?? "",
    });
  }

  function close(next: boolean) {
    if (busy) return;
    if (!next) setDraft(null);
    onOpenChange(next);
  }

  /** Mirror the API's own two rules so the dialog never shows an impossible pair. */
  function setBidStatus(bidStatus: BidStatus) {
    setDraft((current) =>
      current ? { ...current, bidStatus, outcome: bidStatus === "not_bid" ? "" : current.outcome } : current,
    );
  }

  function setOutcome(outcome: Outcome) {
    setDraft((current) =>
      current ? { ...current, outcome, bidStatus: outcome ? "bid" : current.bidStatus } : current,
    );
  }

  async function save() {
    if (!project || !draft) return;
    setBusy(true);
    await patchBid(
      project,
      {
        initiator: draft.initiator.trim(),
        ...(draft.enteredByRole ? { enteredByRole: draft.enteredByRole } : {}),
        ...(draft.bidDue ? { bidDue: draft.bidDue } : {}),
        assignedEstimator: draft.assignedEstimator,
        bidStatus: draft.bidStatus,
        outcome: draft.outcome,
        p21OrderNo: draft.p21OrderNo.trim(),
      },
      () => {
        toast.success(`${project.code} updated`);
        setDraft(null);
        onOpenChange(false);
        onSaved();
      },
    );
    setBusy(false);
  }

  if (!project || !draft) {
    return (
      <Dialog open={open} onOpenChange={close}>
        <DialogContent />
      </Dialog>
    );
  }

  const notBid = draft.bidStatus === "not_bid";

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent showCloseButton={!busy}>
        <DialogHeader>
          <DialogTitle>Update {project.code}</DialogTitle>
          <DialogDescription>
            {project.name}
            {project.gc ? ` · ${project.gc}` : ""}
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Entered by">
            <Input
              value={draft.initiator}
              disabled={busy}
              onChange={(event) =>
                setDraft((current) => (current ? { ...current, initiator: event.target.value } : current))
              }
            />
          </Field>

          <Field label="Date entered">
            <span className="tnum rounded-lg border border-subtle bg-panel-muted px-3 py-2.5 text-[13px] font-medium text-tx-muted">
              {new Date(project.createdAt).toLocaleDateString()}
            </span>
          </Field>

          <div className="sm:col-span-2">
            <Field label="Their team">
              <Chips
                disabled={busy}
                value={draft.enteredByRole}
                onPick={(enteredByRole) =>
                  setDraft((current) => (current ? { ...current, enteredByRole } : current))
                }
                options={ROLES.map((role) => ({ value: role, label: role }))}
              />
            </Field>
          </div>

          <Field label="Due date">
            <Input
              type="date"
              value={draft.bidDue}
              disabled={busy}
              onChange={(event) =>
                setDraft((current) => (current ? { ...current, bidDue: event.target.value } : current))
              }
            />
          </Field>

          <Field label="P21 order">
            <Input
              value={draft.p21OrderNo}
              placeholder="e.g. SO-44812"
              disabled={busy}
              onChange={(event) =>
                setDraft((current) => (current ? { ...current, p21OrderNo: event.target.value } : current))
              }
            />
          </Field>

          <div className="sm:col-span-2">
            <Field label="Assigned estimator">
              <select
                value={draft.assignedEstimator}
                disabled={busy}
                onChange={(event) =>
                  setDraft((current) =>
                    current ? { ...current, assignedEstimator: event.target.value } : current,
                  )
                }
                className="rounded-lg border border-subtle bg-background px-3 py-2.5 text-[13px] font-medium text-tx-primary outline-none focus:border-brand-primary/30 focus:ring-2 focus:ring-brand-border"
              >
                <option value="">Unassigned</option>
                {(data?.users ?? []).map((person) => (
                  <option key={person.email} value={person.email}>
                    {person.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Bid status">
            <Chips
              disabled={busy}
              value={draft.bidStatus}
              onPick={setBidStatus}
              options={[
                { value: "bid", label: "Bid", icon: <PaperPlaneTilt size={14} weight="duotone" /> },
                { value: "not_bid", label: "Not bid", icon: <Prohibit size={14} weight="duotone" /> },
              ]}
            />
          </Field>

          <Field label="Outcome">
            <Chips
              disabled={busy || notBid}
              value={draft.outcome}
              onPick={setOutcome}
              options={[
                { value: "", label: "Open", icon: <Minus size={14} weight="bold" /> },
                { value: "won", label: "Won", icon: <Trophy size={14} weight="duotone" /> },
                { value: "lost", label: "Lost", icon: <ArrowBendDownLeft size={14} weight="duotone" /> },
              ]}
            />
          </Field>
        </div>

        <p
          className={cn(
            "text-[12px] leading-relaxed",
            notBid
              ? "text-tx-secondary"
              : draft.outcome === "won"
                ? "text-status-success"
                : draft.outcome === "lost"
                  ? "text-status-error"
                  : "text-tx-muted",
          )}
        >
          {notBid
            ? "Not bid is kept separate from Won and Lost. This job is never counted in win rate."
            : draft.outcome
              ? "Outcome recorded. The job counts in win rate."
              : "Open — no outcome yet. Record one when the GC comes back."}
        </p>

        <DialogFooter>
          <button
            type="button"
            onClick={() => close(false)}
            disabled={busy}
            className="rounded-lg border border-subtle bg-background px-4 py-2 text-[13px] font-bold text-tx-secondary shadow-1 transition-colors hover:bg-panel-muted"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={busy}
            className="rounded-lg bg-brand-primary px-4 py-2 text-[13px] font-bold text-white shadow-1 transition-colors hover:bg-brand-primary/90 disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save changes"}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
