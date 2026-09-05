"use client";

import { useRef, useState } from "react";
import useSWR from "swr";
import {
  Books,
  UploadSimple,
  Trash,
  CheckCircle,
  Plus,
  Envelope,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/status-badge";
import { formatMoney } from "@/lib/format";
import type { PriceBookDetail, PriceBooksResponse } from "@/lib/types";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { cn } from "@/lib/utils";

function formatMultiplier(value: number | null | undefined): string {
  return typeof value === "number" && !Number.isNaN(value) ? value.toFixed(3) : "—";
}

function categoryLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

export function PriceBooksClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data, error, isLoading, mutate } = useSWR<PriceBooksResponse>(
    "/api/proxy/price-books",
    proxyFetcher,
  );
  const { data: detail, mutate: mutateDetail } = useSWR<PriceBookDetail>(
    selectedId ? `/api/proxy/price-books/${selectedId}` : null,
    proxyFetcher,
  );

  const books = data?.priceBooks ?? [];
  const selected = detail?.priceBook;
  const categoryEntries = Object.entries(selected?.categories ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const usesCategoryMultipliers = categoryEntries.length > 0;

  async function upload(files: FileList | null) {
    if (!files?.length || !selectedId) return;
    const file = files[0];
    const form = new FormData();
    form.append("file", file);

    // A price book is a large PDF. Without this the button simply sat there.
    setUploading(file.name);
    try {
      await proxyMutate(`/api/proxy/price-books/${selectedId}/file`, { form });
      toast.success("Sheet uploaded", {
        description: "Claude has been queued to read it into the catalog.",
      });
      mutate();
      mutateDetail();
    } catch (problem) {
      toast.error("Upload failed", { description: errorMessage(problem) });
    } finally {
      setUploading(null);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function patch(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/price-books/${selectedId}`, { method: "PATCH", body });
      toast.success(success);
      mutate();
      mutateDetail();
    } catch (problem) {
      toast.error("Could not save that", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  /** Record that purchasing has been asked for a newer sheet. Sends nothing. */
  async function requestSheet() {
    if (!selected) return;
    const note = `Updated sheet requested ${new Date().toLocaleDateString()}`;
    try {
      await proxyMutate(`/api/proxy/price-books/${selectedId}`, {
        method: "PATCH",
        body: { note },
      });
      toast.success("Request recorded against the program", {
        description: "Nothing was emailed — tell purchasing directly.",
      });
      mutate();
      mutateDetail();
    } catch (problem) {
      toast.error("Could not record the request", { description: errorMessage(problem) });
    }
  }

  async function markReviewed() {
    try {
      await proxyMutate(`/api/proxy/price-books/${selectedId}/mark-reviewed`);
      toast.success("Marked as reviewed today");
      mutate();
      mutateDetail();
    } catch (problem) {
      toast.error("Could not record the review", { description: errorMessage(problem) });
    }
  }

  async function remove() {
    if (!selected) return;
    if (
      !window.confirm(
        `Remove the ${selected.displayName ?? selected.vendor} program? Parts priced under it are kept and marked orphaned.`,
      )
    ) {
      return;
    }
    try {
      await proxyMutate(`/api/proxy/price-books/${selectedId}`, { method: "DELETE" });
      toast.success(`${selected.vendor} removed`, {
        description: "Parts priced under it are kept and marked orphaned.",
      });
      setSelectedId(null);
      mutate();
    } catch (problem) {
      toast.error("Could not remove that program", { description: errorMessage(problem) });
    }
  }

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/price-books", {
        body: {
          vendor: String(form.get("vendor") ?? "").trim(),
          program: String(form.get("program") ?? "").trim() || null,
          multiplier: form.get("multiplier") ? Number(form.get("multiplier")) : null,
          effective: String(form.get("effective") ?? "") || null,
        },
      });
      toast.success("Program added");
      setAdding(false);
      mutate();
    } catch (problem) {
      toast.error("Could not add that program", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="relative flex min-h-0 flex-1 flex-col gap-6 overflow-auto p-8 bg-background lg:flex-row lg:overflow-hidden">
      {error && (
        <div className="absolute inset-x-8 top-8 z-10 rounded-lg px-4 py-3 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
          Could not load price books: {error.message}
        </div>
      )}
      <section className="flex shrink-0 flex-col gap-4 lg:w-[360px]">
        <div className="flex items-end justify-between">
          <div>
            <h1 className="text-[20px] font-bold text-tx-primary tracking-tight">Price books</h1>
            <p className="mt-1 text-[13px] font-medium text-tx-secondary">
              {data?.counts.total ?? 0} programs · {data?.counts.stale ?? 0} past review
            </p>
          </div>
          <button
            onClick={() => setAdding((current) => !current)}
            className="flex items-center gap-1.5 rounded-md px-3.5 py-2 text-[12.5px] font-semibold border border-subtle bg-panel shadow-sm hover:bg-panel-muted transition-colors text-tx-primary"
          >
            <Plus size={14} weight="bold" />
            Add
          </button>
        </div>

        {adding && (
          <form
            onSubmit={create}
            className="animate-fade-in flex flex-col gap-3 rounded-xl p-4 bg-panel border border-subtle shadow-sm"
          >
            {[
              { name: "vendor", placeholder: "Vendor key, e.g. hager", required: true },
              { name: "program", placeholder: "Program name" },
              { name: "multiplier", placeholder: "Multiplier, e.g. 0.29", type: "number" },
              { name: "effective", placeholder: "Effective date", type: "date" },
            ].map((field) => (
              <input
                key={field.name}
                name={field.name}
                type={field.type ?? "text"}
                step="0.001"
                required={field.required}
                placeholder={field.placeholder}
                className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm"
              />
            ))}
            <button
              type="submit"
              className="rounded-md py-2.5 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
            >
              Add program
            </button>
          </form>
        )}

        <div className="min-h-[160px] flex-1 overflow-auto rounded-xl bg-panel border border-subtle shadow-sm">
          {isLoading && books.length === 0 && (
            <p className="px-4 py-10 text-center text-[13px] font-medium text-tx-muted">
              Reading the programs…
            </p>
          )}
          {!isLoading && !error && books.length === 0 && (
            <div className="grid place-items-center gap-2 px-5 py-12 text-center">
              <span className="text-[14px] font-semibold text-tx-primary">No price books yet</span>
              <span className="text-[12.5px] font-medium text-tx-secondary">
                Add a vendor program, then upload its sheet. Every quote prices off these.
              </span>
            </div>
          )}
          {books.map((book) => (
            <button
              key={book.id}
              onClick={() => setSelectedId(book.id)}
              className={cn(
                "flex w-full items-center gap-4 border-b border-subtle px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-panel-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brand-border",
                selectedId === book.id && "bg-brand-soft/30 border-l-[3px] border-l-brand-primary",
                selectedId !== book.id && "border-l-[3px] border-l-transparent"
              )}
            >
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate text-[13.5px] font-semibold capitalize text-tx-primary">
                  {book.displayName ?? book.vendor}
                </span>
                <span className="truncate text-[11.5px] font-medium text-tx-secondary mt-0.5">
                  {book.program ?? book.kind ?? "—"}
                </span>
                {(book.stale || book.undated) && (
                  <StatusBadge variant="caution" className="mt-1.5 w-fit">
                    {book.undated ? "No effective date" : "Past review"}
                  </StatusBadge>
                )}
                <span className="mt-1 block text-[11px] font-medium text-tx-muted">
                  {book.undated
                    ? "Upload or record an effective date"
                    : book.stale
                      ? `Effective ${book.effective}`
                      : `Reviewed ${book.lastReviewed ?? book.effective}`}
                </span>
              </span>
              <span className="tnum text-[15px] font-bold text-tx-primary">
                {book.categories && Object.keys(book.categories).length > 0
                  ? "Per cat."
                  : formatMultiplier(book.multiplier)}
              </span>
            </button>
          ))}
        </div>
      </section>

      <section className="flex min-w-0 flex-1 flex-col rounded-xl bg-panel border border-subtle shadow-sm lg:overflow-auto">
        {!selected ? (
          <div className="grid flex-1 place-items-center gap-2 px-6 py-16 text-center">
            <Books size={32} weight="duotone" className="text-tx-muted mb-2" />
            <span className="text-[14px] font-semibold text-tx-primary">Select a price book</span>
            <span className="max-w-[320px] text-[13px] font-medium text-tx-secondary">
              Pick a program from the list to review its multiplier, parts, and upload a newer sheet.
            </span>
          </div>
        ) : (
          <div className="p-6 sm:p-8">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="text-[24px] font-bold tracking-tight text-tx-primary capitalize">
                  {selected.displayName ?? selected.vendor}
                </h2>
                <p className="mt-1.5 text-[13.5px] font-medium text-tx-secondary">
                  {selected.program ?? "—"}
                  {selected.account ? ` · account ${selected.account}` : ""}
                </p>
              </div>
              <div className="text-right">
                <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-1">
                  {usesCategoryMultipliers ? "Category multipliers" : "Multiplier"}
                </span>
                <span className="tnum text-[36px] font-bold leading-none text-brand-primary tracking-tight">
                  {usesCategoryMultipliers ? "Per category" : formatMultiplier(selected.multiplier)}
                </span>
              </div>
            </div>

            <div className="mt-8 grid grid-cols-2 gap-4 rounded-xl bg-panel-muted border border-subtle p-5 shadow-sm xl:grid-cols-4">
              {[
                ["Effective", selected.effective ?? "not recorded"],
                ["Protected through", selected.protectedThrough ?? "—"],
                ["Last reviewed", selected.lastReviewed ?? "never"],
                ["Steward", selected.steward ?? "UNASSIGNED"],
              ].map(([label, value]) => (
                <div key={label} className="flex flex-col gap-1">
                  <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                    {label}
                  </span>
                  <span
                    className={cn(
                      "text-[14px] font-semibold",
                      value === "UNASSIGNED" || value === "never" ? "text-status-error" : "text-tx-primary"
                    )}
                  >
                    {value}
                  </span>
                </div>
              ))}
            </div>

            {(selected.stale || selected.undated) && (
              <p className="mt-4 rounded-md px-4 py-3 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
                {selected.undated
                  ? "No effective date on file, so staleness cannot be judged."
                  : `This sheet is ${selected.ageDays} days old. Quotes priced from it may be wrong.`}{" "}
                No refresh owner has been assigned yet.
              </p>
            )}

            <div className="mt-8 flex flex-wrap items-end gap-3">
              {usesCategoryMultipliers ? (
                <div className="flex w-full flex-col gap-3">
                  <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    Hager Advantage Program tiers
                  </span>
                  <div
                    className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3"
                    style={{ maxWidth: 720 }}
                  >
                    {categoryEntries.map(([key, value]) => (
                      <label key={key} className="flex flex-col gap-1.5">
                        <span className="text-[12.5px] font-medium text-tx-secondary">
                          {categoryLabel(key)}
                        </span>
                        <input
                          type="number"
                          step="0.001"
                          defaultValue={value}
                          key={`${selected.id}-${key}`}
                          disabled={busy}
                          aria-label={`${categoryLabel(key)} multiplier`}
                          onBlur={(event) => {
                            const next = Number(event.target.value);
                            if (event.target.value.trim() === "" || Number.isNaN(next)) return;
                            if (next === value) return;
                            const categories = {
                              ...(selected.categories ?? {}),
                              [key]: next,
                            };
                            patch({ categories }, `${categoryLabel(key)} multiplier updated`);
                          }}
                          className="tnum rounded-md px-3 py-2 text-[13.5px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm"
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ) : (
                <label className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                    Multiplier
                  </span>
                  <input
                    type="number"
                    step="0.001"
                    defaultValue={selected.multiplier ?? ""}
                    key={selected.id}
                    disabled={busy}
                    aria-label="Multiplier"
                    onBlur={(event) => {
                      const next = Number(event.target.value);
                      if (event.target.value.trim() === "") return;
                      if (!Number.isNaN(next) && next !== selected.multiplier) {
                        patch({ multiplier: next }, "Multiplier updated and parts repriced");
                      }
                    }}
                    className="tnum w-[120px] rounded-md px-3 py-2 text-[13.5px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm"
                  />
                </label>
              )}

              <input
                ref={fileRef}
                type="file"
                accept="application/pdf,.pdf,.csv,.xlsx"
                aria-label="Upload a newer price sheet"
                className="hidden"
                onChange={(event) => upload(event.target.files)}
              />
              <button
                onClick={() => fileRef.current?.click()}
                disabled={!!uploading}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-semibold disabled:opacity-60 bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
              >
                <UploadSimple size={15} weight="bold" />
                Upload a newer sheet
              </button>
              <button
                onClick={requestSheet}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
              >
                <Envelope size={15} weight="duotone" />
                Request an updated sheet
              </button>
              <button
                onClick={markReviewed}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
              >
                <CheckCircle size={15} weight="duotone" />
                Mark as reviewed today
              </button>
              <span className="flex-1" />
              <button
                onClick={remove}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-status-error/30 text-status-error hover:bg-status-error-soft transition-colors shadow-sm"
              >
                <Trash size={15} weight="duotone" />
                Remove
              </button>
            </div>

            <p className="mt-4 text-[12.5px] font-medium text-tx-muted leading-relaxed max-w-[800px]">
              {usesCategoryMultipliers
                ? "Category multipliers sync to vendor_tiers.json and drive list × category pricing."
                : "Changing the multiplier reprices every part on this program."}{" "}
              Uploading a sheet queues Claude to read it into the catalog, so the next bid prices off
              the newest data.
            </p>

            <div className="mt-10">
              <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-3">
                Priced under this program ({detail?.partCount ?? 0})
              </span>

              {(detail?.parts ?? []).length === 0 ? (
                <p className="mt-2 text-[12.5px] font-medium text-tx-secondary">
                  No catalog parts point at this program yet.
                </p>
              ) : (
                <div className="mt-3 overflow-x-auto rounded-xl border border-subtle shadow-sm bg-background">
                  <div
                    className="grid gap-4 border-b border-subtle px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest text-tx-muted bg-panel/50"
                    style={{
                      minWidth: 620,
                      gridTemplateColumns: "230px minmax(160px,1fr) 100px 100px",
                    }}
                  >
                    <span>Part</span>
                    <span>Description</span>
                    <span className="text-right">List</span>
                    <span className="text-right">Net</span>
                  </div>
                  <div className="divide-y divide-subtle">
                    {(detail?.parts ?? []).map((part) => (
                      <div
                        key={part.id}
                        className="grid items-center gap-4 px-4 py-3 transition-colors hover:bg-panel-muted"
                        style={{
                          minWidth: 620,
                          gridTemplateColumns: "230px minmax(160px,1fr) 100px 100px",
                        }}
                      >
                        <span className="truncate text-[13px] font-semibold text-tx-primary">{part.part}</span>
                        <span className="truncate text-[12.5px] font-medium text-tx-secondary">
                          {part.description}
                        </span>
                        <span className="tnum text-right text-[13px] font-medium text-tx-muted">
                          {part.listPrice === null ? "—" : `$${formatMoney(part.listPrice)}`}
                        </span>
                        <span className="tnum text-right text-[13px] font-bold text-tx-primary">
                          {part.cost === null ? "—" : `$${formatMoney(part.cost)}`}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
