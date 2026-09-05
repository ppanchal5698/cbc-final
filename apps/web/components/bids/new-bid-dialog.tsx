"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { useDialog } from "@/hooks/use-dialog";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import type { Project } from "@/lib/types";

interface Field {
  key: string;
  label: string;
  placeholder: string;
  required?: boolean;
  hint?: string;
  type?: string;
  list?: string;
}

/** Sales-queue names from the estimator session (FR-10). Free text still allowed. */
const SALES_INITIATORS = ["Kellan", "Matt", "Rebecca", "Tina"] as const;

const FIELDS: Field[] = [
  { key: "name", label: "Job name", placeholder: "e.g. Burger King #2379 — exterior & interior", required: true },
  { key: "brand", label: "Brand", placeholder: "e.g. Burger King" },
  { key: "location", label: "Location", placeholder: "e.g. Cortlandt Manor, NY" },
  { key: "state", label: "State", placeholder: "e.g. NY", hint: "Two letters. Tax applies to OH and KY only." },
  { key: "gc", label: "General contractor", placeholder: "e.g. Cortlandt Builders LLC" },
  {
    key: "initiator",
    label: "Requested by",
    placeholder: "e.g. Rebecca",
    hint: "Quote returns to this person in the sales queue — not a group email.",
    list: "sales-initiators",
  },
  { key: "architect", label: "Architect", placeholder: "e.g. Coralic LLC" },
  { key: "bidDue", label: "Bid due", placeholder: "", type: "date" },
  {
    key: "bidAlternates",
    label: "Alternates noted",
    placeholder: "e.g. Alternate 1, Alternate 2",
    hint: "Optional. Names only at intake — reconciliation rules are still pending (Matrix 4.1).",
  },
];

export function NewBidDialog() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<"one_off" | "templated">("one_off");
  const [autopilot, setAutopilot] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const close = useCallback(() => setOpen(false), []);
  const dialogRef = useDialog<HTMLFormElement>(open, close);

  async function create(event: React.FormEvent) {
    event.preventDefault();

    const errors: Record<string, string> = {};
    if (!values.name?.trim()) {
      errors.name = "Job name is required.";
    }
    if (values.state?.trim() && values.state.trim().length !== 2) {
      errors.state = "Use a two-letter state code (e.g. OH).";
    }
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) return;

    const body: Record<string, unknown> = Object.fromEntries(
      Object.entries(values)
        .filter(([key, value]) => key !== "bidAlternates" && value.trim() !== "")
        .map(([key, value]) => [key, value]),
    );
    if (typeof body.state === "string") body.state = body.state.toUpperCase().slice(0, 2);

    const alternates = (values.bidAlternates ?? "")
      .split(",")
      .map((part) => part.trim())
      .filter(Boolean);
    if (alternates.length) body.bidAlternates = alternates;

    setBusy(true);
    try {
      const project = await proxyMutate<Project>("/api/proxy/projects", {
        body: { ...body, mode, autopilot },
      });
      toast.success(`${project.code} created`, {
        description: "Add bid PDFs when ready — phone-ins can stay empty until files arrive.",
      });
      setOpen(false);
      setValues({});
      setMode("one_off");
      setAutopilot(false);
      router.push(`/bids/${project.code}/intake`);
      router.refresh();
    } catch (problem) {
      toast.error("Could not create the bid", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-bold bg-brand-primary text-white hover:bg-brand-primary/90 transition-colors shadow-sm"
      >
        <Plus size={16} weight="bold" />
        Create bid request
      </button>
    );
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center overflow-auto p-4 sm:p-6 bg-black/55 backdrop-blur-sm"
      onClick={(event) => event.target === event.currentTarget && setOpen(false)}
    >
      <form
        ref={dialogRef}
        onSubmit={create}
        noValidate
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-bid-title"
        className="anim-popin my-auto w-full max-w-[620px] rounded-2xl p-6 sm:p-8 bg-panel border border-subtle shadow-2xl"
      >
        <h2 id="new-bid-title" className="text-[18px] font-bold text-tx-primary tracking-tight">
          Create bid request
        </h2>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary leading-relaxed">
          For email or phone-in requests (NR-5). A CBC number is assigned automatically.
          Only job name is required — after you upload the bid PDF, empty fields here
          are filled from the drawings with page citations before take-off continues.
        </p>

        <datalist id="sales-initiators">
          {SALES_INITIATORS.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>

        <div className="mt-6 grid gap-x-5 gap-y-4 sm:grid-cols-2">
          {FIELDS.map((field) => (
            <label
              key={field.key}
              htmlFor={`new-bid-${field.key}`}
              className={
                field.key === "name" || field.key === "bidAlternates"
                  ? "block sm:col-span-2"
                  : "block"
              }
            >
              <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                {field.label}
                {field.required && <span className="text-status-error"> *</span>}
              </span>
              <input
                id={`new-bid-${field.key}`}
                type={field.type ?? "text"}
                list={field.list}
                aria-invalid={fieldErrors[field.key] ? true : undefined}
                aria-describedby={
                  fieldErrors[field.key]
                    ? `new-bid-${field.key}-error`
                    : field.hint
                      ? `new-bid-${field.key}-hint`
                      : undefined
                }
                placeholder={field.placeholder}
                value={values[field.key] ?? ""}
                onChange={(event) => {
                  setValues((current) => ({ ...current, [field.key]: event.target.value }));
                  if (fieldErrors[field.key]) {
                    setFieldErrors((current) => {
                      const next = { ...current };
                      delete next[field.key];
                      return next;
                    });
                  }
                }}
                className={`mt-1.5 w-full rounded-lg px-3 py-2.5 text-[13.5px] font-medium outline-none placeholder:italic placeholder:opacity-50 transition-all shadow-sm ${
                  fieldErrors[field.key]
                    ? "bg-status-error-soft border border-status-error/30 text-status-error focus:ring-2 focus:ring-status-error/30"
                    : "bg-background border border-subtle text-tx-primary focus:ring-2 focus:ring-brand-border focus:border-brand-primary/30"
                }`}
              />
              {field.key === "initiator" && (
                <span className="mt-2 flex flex-wrap gap-1.5">
                  {SALES_INITIATORS.map((name) => (
                    <button
                      key={name}
                      type="button"
                      onClick={() => setValues((current) => ({ ...current, initiator: name }))}
                      className={`rounded-lg px-2.5 py-1 text-[11px] font-bold border transition-colors shadow-sm ${
                        values.initiator === name
                          ? "bg-brand-primary/10 border-brand-primary/20 text-brand-primary"
                          : "bg-background border-subtle text-tx-muted hover:text-tx-primary hover:bg-panel-muted"
                      }`}
                    >
                      {name}
                    </button>
                  ))}
                </span>
              )}
              {fieldErrors[field.key] && (
                <span
                  id={`new-bid-${field.key}-error`}
                  className="mt-1.5 block text-[11.5px] font-medium text-status-error"
                >
                  {fieldErrors[field.key]}
                </span>
              )}
              {field.hint && (
                <span
                  id={`new-bid-${field.key}-hint`}
                  className="mt-1.5 block text-[11px] font-medium text-tx-muted"
                >
                  {field.hint}
                </span>
              )}
            </label>
          ))}
        </div>

        <fieldset className="mt-6 rounded-xl px-4 py-3.5 bg-panel-muted border border-subtle shadow-sm">
          <legend className="px-1 text-[11px] font-bold uppercase tracking-widest text-tx-muted">
            Estimating mode
          </legend>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:gap-4">
            <label className="flex cursor-pointer items-start gap-2.5 flex-1">
              <input
                type="radio"
                name="mode"
                checked={mode === "one_off"}
                onChange={() => setMode("one_off")}
                className="mt-0.5 h-4 w-4 border-subtle text-brand-primary focus:ring-brand-primary"
              />
              <span className="leading-snug">
                <span className="block text-[13px] font-bold text-tx-primary">One-off</span>
                <span className="block text-[12px] font-medium text-tx-secondary">
                  Build from scratch (Kevin). Default for unique jobs.
                </span>
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2.5 flex-1">
              <input
                type="radio"
                name="mode"
                checked={mode === "templated"}
                onChange={() => setMode("templated")}
                className="mt-0.5 h-4 w-4 border-subtle text-brand-primary focus:ring-brand-primary"
              />
              <span className="leading-snug">
                <span className="block text-[13px] font-bold text-tx-primary">Templated</span>
                <span className="block text-[12px] font-medium text-tx-secondary">
                  Start from a prior quote and trim (Shanna / FR-11).
                </span>
              </span>
            </label>
          </div>
        </fieldset>

        <label
          className="mt-4 flex cursor-pointer items-start gap-3 rounded-xl px-4 py-3.5 bg-panel-muted border border-subtle hover:bg-background/50 transition-colors shadow-sm"
        >
          <input
            type="checkbox"
            checked={autopilot}
            onChange={(event) => setAutopilot(event.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-subtle text-brand-primary focus:ring-brand-primary"
          />
          <span className="flex flex-col leading-snug gap-1">
            <span className="text-[13.5px] font-bold text-tx-primary tracking-tight">Run the whole pipeline on upload</span>
            <span className="text-[12px] font-medium text-tx-secondary leading-relaxed">
              One pass from intake to a draft proposal, without stopping for you to
              confirm the openings. They are priced before anyone checks them, and
              anything uncertain is flagged for review at the end. Nothing is ever sent.
            </span>
          </span>
        </label>

        <div className="mt-8 flex items-center justify-end gap-3 pt-4 border-t border-subtle">
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-lg px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted hover:text-tx-primary transition-colors shadow-sm"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg px-5 py-2 text-[13px] font-bold disabled:opacity-50 bg-brand-primary text-white hover:bg-brand-primary/90 transition-colors shadow-sm"
          >
            {busy ? "Creating…" : "Create bid request"}
          </button>
        </div>
      </form>
    </div>
  );
}
