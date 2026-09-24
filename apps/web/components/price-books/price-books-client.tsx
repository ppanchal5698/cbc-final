"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  Books,
  UploadSimple,
  Trash,
  CheckCircle,
  Plus,
  Envelope,
  DownloadSimple,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { StatusBadge } from "@/components/ui/status-badge";
import { formatMoney } from "@/lib/format";
import type {
  Job,
  PriceBook,
  PriceBookDetail,
  PriceBookUploadResponse,
  PriceBooksResponse,
} from "@/lib/types";

import { errorMessage, proxyFetch, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { cn } from "@/lib/utils";

function formatMultiplier(value: number | null | undefined): string {
  return typeof value === "number" && !Number.isNaN(value) ? value.toFixed(3) : "—";
}

function categoryLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function kindLabel(kind: string | null | undefined): string {
  return kind === "multiplier_sheet" ? "Multiplier sheet" : "Price book";
}

function isActiveJob(job: Job | null | undefined): boolean {
  return job?.status === "queued" || job?.status === "running";
}

function jobBadgeVariant(status: string | undefined): "progress" | "ok" | "review" | "neutral" {
  if (status === "queued" || status === "running") return "progress";
  if (status === "done") return "ok";
  if (status === "failed" || status === "dead" || status === "cancelled") return "review";
  return "neutral";
}

function parseBadgeVariant(state: string | undefined): "progress" | "ok" | "review" | "neutral" {
  if (state === "queued" || state === "running") return "progress";
  if (state === "parsed" || state === "ready") return "ok";
  if (state === "failed") return "review";
  return "neutral";
}

function fieldClassName() {
  return "rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm";
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function PriceBooksClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<string | null>(null);
  const [trackedJobIds, setTrackedJobIds] = useState<{ index?: string; parse?: string }>({});
  const fileRef = useRef<HTMLInputElement>(null);
  const toastedJobs = useRef<Set<string>>(new Set());

  const { data, error, isLoading, mutate } = useSWR<PriceBooksResponse>(
    "/api/proxy/price-books",
    proxyFetcher,
  );

  const jobsActive = Boolean(trackedJobIds.index || trackedJobIds.parse);

  const { data: detail, mutate: mutateDetail } = useSWR<PriceBookDetail>(
    selectedId ? `/api/proxy/price-books/${selectedId}` : null,
    proxyFetcher,
    {
      refreshInterval: (latest) => {
        const parseState = latest?.priceBook?.parse?.state;
        const parseBusy = parseState === "queued" || parseState === "running";
        return parseBusy || jobsActive ? 4000 : 0;
      },
    },
  );

  const books = data?.priceBooks ?? [];
  const selected = detail?.priceBook;
  const devFreshnessControls =
    data?.devFreshnessControls ?? selected?.devFreshnessControls ?? false;
  const categoryEntries = Object.entries(selected?.categories ?? {}).sort(([a], [b]) =>
    a.localeCompare(b),
  );
  const usesCategoryMultipliers = categoryEntries.length > 0;

  const indexJobId = trackedJobIds.index;
  const parseJobId = trackedJobIds.parse;

  const { data: indexJob } = useSWR<Job>(
    indexJobId ? `/api/proxy/jobs/${indexJobId}` : null,
    proxyFetcher,
    { refreshInterval: (latest) => (isActiveJob(latest) ? 3000 : 0) },
  );
  const { data: parseJob } = useSWR<Job>(
    parseJobId ? `/api/proxy/jobs/${parseJobId}` : null,
    proxyFetcher,
    { refreshInterval: (latest) => (isActiveJob(latest) ? 3000 : 0) },
  );

  useEffect(() => {
    if (!indexJob || isActiveJob(indexJob) || toastedJobs.current.has(indexJob.id)) return;
    toastedJobs.current.add(indexJob.id);
    if (indexJob.status === "done") {
      toast.success("Page index ready", {
        description: "Catalog search can find pages in this sheet.",
      });
    } else if (indexJob.status === "failed" || indexJob.status === "dead") {
      toast.error("Page index failed", { description: indexJob.error ?? indexJob.status });
    }
    setTrackedJobIds((prev) => ({ ...prev, index: undefined }));
    mutate();
    mutateDetail();
  }, [indexJob, mutate, mutateDetail]);

  useEffect(() => {
    if (!parseJob || isActiveJob(parseJob) || toastedJobs.current.has(parseJob.id)) return;
    toastedJobs.current.add(parseJob.id);
    if (parseJob.status === "done") {
      toast.success("Sheet parse finished", {
        description: "Parsed page blocks are available for this program.",
      });
    } else if (parseJob.status === "failed" || parseJob.status === "dead") {
      toast.error("Sheet parse failed", { description: parseJob.error ?? parseJob.status });
    }
    setTrackedJobIds((prev) => ({ ...prev, parse: undefined }));
    mutate();
    mutateDetail();
  }, [parseJob, mutate, mutateDetail]);

  async function upload(files: FileList | null) {
    if (!files?.length || !selectedId) return;
    const file = files[0];
    const form = new FormData();
    form.append("file", file);

    setUploading(file.name);
    try {
      const result = await proxyMutate<PriceBookUploadResponse>(
        `/api/proxy/price-books/${selectedId}/file`,
        { form },
      );
      const nextTrack: { index?: string; parse?: string } = {};
      if (result.job?.id) nextTrack.index = result.job.id;
      if (result.parseJob?.id) nextTrack.parse = result.parseJob.id;
      setTrackedJobIds(nextTrack);

      const parseQueued = Boolean(result.parseJob);
      toast.success("Sheet uploaded", {
        description: parseQueued
          ? "Queued page index for this sheet."
          : "Queued page index for catalog search.",
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

  async function setFreshness(reference: "fresh" | "stale") {
    if (!selectedId) return;
    const today = todayIso();
    const body =
      reference === "fresh"
        ? { lastReviewed: today, effective: selected?.effective ?? today }
        : { lastReviewed: "2017-01-01", effective: selected?.effective ?? "2017-01-01" };
    await patch(
      body,
      reference === "fresh" ? "Program marked fresh (dev)" : "Program marked stale (dev)",
    );
  }

  async function markAllFresh() {
    const targets = books.filter((book) => book.stale || book.undated);
    if (!targets.length) {
      toast.message("Every program is already within the review window");
      return;
    }
    setBusy(true);
    const today = todayIso();
    try {
      for (const book of targets) {
        await proxyMutate(`/api/proxy/price-books/${book.id}`, {
          method: "PATCH",
          body: {
            lastReviewed: today,
            ...(book.undated ? { effective: today } : {}),
          },
        });
      }
      toast.success(`Marked ${targets.length} program${targets.length === 1 ? "" : "s"} fresh (dev)`);
      mutate();
      mutateDetail();
    } catch (problem) {
      toast.error("Could not mark every program fresh", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function downloadSheet() {
    if (!selectedId) return;
    const response = await proxyFetch(`/api/proxy/price-books/${selectedId}/file`);
    if (!response.ok) {
      toast.error("Could not download the sheet", {
        description:
          response.status === 404
            ? "No sheet has been uploaded for this program."
            : response.statusText,
      });
      return;
    }
    const disposition = response.headers.get("content-disposition") ?? "";
    const filename =
      /filename="?([^";]+)"?/.exec(disposition)?.[1] ??
      `${selected?.vendor ?? "price-book"}-sheet`;
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
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
      setTrackedJobIds({});
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
          kind: String(form.get("kind") ?? "price_book") || "price_book",
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

  function blurPatch(
    key: keyof PriceBook,
    raw: string,
    current: string | null | undefined,
    success: string,
    asNullWhenEmpty = true,
  ) {
    const next = raw.trim();
    const normalized = asNullWhenEmpty && next === "" ? null : next;
    const previous = current ?? null;
    if (normalized === previous) return;
    patch({ [key]: normalized }, success);
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
            {devFreshnessControls && (data?.counts.stale ?? 0) > 0 && (
              <button
                type="button"
                onClick={markAllFresh}
                disabled={busy}
                className="mt-2 text-[12px] font-semibold text-brand-primary hover:underline disabled:opacity-60"
              >
                Mark all fresh (dev)
              </button>
            )}
          </div>
          <button
            onClick={() => setAdding((current) => !current)}
            className="flex items-center gap-1.5 rounded-md px-3.5 py-2 text-[12.5px] font-semibold border border-subtle bg-panel shadow-sm hover:bg-panel-muted transition-colors text-tx-primary"
          >
            <Plus size={14} weight="bold" />
            Add
          </button>
        </div>

        {data?.stewardship?.note && (
          <p className="rounded-md px-3 py-2 text-[12px] font-medium bg-panel-muted border border-subtle text-tx-secondary">
            {data.stewardship.note}
          </p>
        )}

        {adding && (
          <form
            onSubmit={create}
            className="animate-fade-in flex flex-col gap-3 rounded-xl p-4 bg-panel border border-subtle shadow-sm"
          >
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Kind
              </span>
              <select
                name="kind"
                defaultValue="price_book"
                className={fieldClassName()}
                aria-label="Program kind"
              >
                <option value="price_book">Price book</option>
                <option value="multiplier_sheet">Multiplier sheet</option>
              </select>
            </label>
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
                className={fieldClassName()}
              />
            ))}
            <button
              type="submit"
              disabled={busy}
              className="rounded-md py-2.5 text-[13px] font-semibold disabled:opacity-60 bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
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
              onClick={() => {
                setSelectedId(book.id);
                setTrackedJobIds({});
              }}
              className={cn(
                "flex w-full items-center gap-4 border-b border-subtle px-4 py-3 text-left transition-colors last:border-b-0 hover:bg-panel-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-brand-border",
                selectedId === book.id && "bg-brand-soft/30 border-l-[3px] border-l-brand-primary",
                selectedId !== book.id && "border-l-[3px] border-l-transparent",
              )}
            >
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate text-[13.5px] font-semibold capitalize text-tx-primary">
                  {book.displayName ?? book.vendor}
                </span>
                <span className="truncate text-[11.5px] font-medium text-tx-secondary mt-0.5">
                  {book.program ?? "—"}
                  {book.kind === "multiplier_sheet" ? " · multiplier sheet" : ""}
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
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h2 className="text-[24px] font-bold tracking-tight text-tx-primary capitalize">
                  {selected.displayName ?? selected.vendor}
                </h2>
                <p className="mt-1.5 text-[13.5px] font-medium text-tx-secondary">
                  {kindLabel(selected.kind)}
                  {selected.account ? ` · account ${selected.account}` : ""}
                </p>
              </div>
              <div className="text-right shrink-0">
                <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-1">
                  {usesCategoryMultipliers ? "Category multipliers" : "Multiplier"}
                </span>
                <span className="tnum text-[36px] font-bold leading-none text-brand-primary tracking-tight">
                  {usesCategoryMultipliers ? "Per category" : formatMultiplier(selected.multiplier)}
                </span>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-2">
              <StatusBadge variant={selected.indexStatus === "ready" ? "ok" : "neutral"}>
                Index: {selected.indexStatus ?? "not built"}
              </StatusBadge>
              {selected.parse?.state && (
                <StatusBadge variant={parseBadgeVariant(selected.parse.state)}>
                  Parse: {selected.parse.state}
                  {typeof selected.parse.pagesDone === "number" &&
                  typeof selected.parse.pages === "number"
                    ? ` ${selected.parse.pagesDone}/${selected.parse.pages}`
                    : ""}
                </StatusBadge>
              )}
              {indexJob && (
                <StatusBadge variant={jobBadgeVariant(indexJob.status)}>
                  index_catalog: {indexJob.status}
                </StatusBadge>
              )}
              {parseJob && (
                <StatusBadge variant={jobBadgeVariant(parseJob.status)}>
                  {parseJob.type}: {parseJob.status}
                </StatusBadge>
              )}
              {selected.filename && (
                <StatusBadge variant="neutral">Sheet: {selected.filename}</StatusBadge>
              )}
            </div>
            {selected.parse?.error && (
              <p className="mt-2 text-[12.5px] font-medium text-status-error">
                Parse error: {selected.parse.error}
              </p>
            )}

            <div className="mt-8 grid grid-cols-1 gap-4 rounded-xl bg-panel-muted border border-subtle p-5 shadow-sm sm:grid-cols-2 xl:grid-cols-3">
              <label className="flex flex-col gap-1.5">
                <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Program
                </span>
                <input
                  key={`${selected.id}-program`}
                  defaultValue={selected.program ?? ""}
                  disabled={busy}
                  aria-label="Program name"
                  onBlur={(event) =>
                    blurPatch("program", event.target.value, selected.program, "Program updated")
                  }
                  className={fieldClassName()}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Effective
                </span>
                <input
                  type="date"
                  key={`${selected.id}-effective`}
                  defaultValue={selected.effective ?? ""}
                  disabled={busy}
                  aria-label="Effective date"
                  onBlur={(event) =>
                    blurPatch(
                      "effective",
                      event.target.value,
                      selected.effective,
                      "Effective date updated",
                    )
                  }
                  className={fieldClassName()}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Protected through
                </span>
                <input
                  type="date"
                  key={`${selected.id}-protected`}
                  defaultValue={selected.protectedThrough ?? ""}
                  disabled={busy}
                  aria-label="Protected through"
                  onBlur={(event) =>
                    blurPatch(
                      "protectedThrough",
                      event.target.value,
                      selected.protectedThrough,
                      "Protection window updated",
                    )
                  }
                  className={fieldClassName()}
                />
              </label>
              <label className="flex flex-col gap-1.5">
                <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Steward
                </span>
                <input
                  key={`${selected.id}-steward`}
                  defaultValue={selected.steward ?? ""}
                  disabled={busy}
                  placeholder="UNASSIGNED"
                  aria-label="Steward"
                  onBlur={(event) =>
                    blurPatch("steward", event.target.value, selected.steward, "Steward updated")
                  }
                  className={fieldClassName()}
                />
              </label>
              <label className="flex flex-col gap-1.5 sm:col-span-2">
                <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                  Note
                </span>
                <input
                  key={`${selected.id}-note`}
                  defaultValue={selected.note ?? ""}
                  disabled={busy}
                  aria-label="Note"
                  onBlur={(event) =>
                    blurPatch("note", event.target.value, selected.note, "Note updated")
                  }
                  className={fieldClassName()}
                />
              </label>
              {devFreshnessControls ? (
                <label className="flex flex-col gap-1.5">
                  <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                    Last reviewed
                  </span>
                  <input
                    type="date"
                    key={`${selected.id}-last-reviewed`}
                    defaultValue={selected.lastReviewed ?? ""}
                    disabled={busy}
                    aria-label="Last reviewed date"
                    onBlur={(event) =>
                      blurPatch(
                        "lastReviewed",
                        event.target.value,
                        selected.lastReviewed,
                        "Last reviewed date updated",
                      )
                    }
                    className={fieldClassName()}
                  />
                </label>
              ) : (
                <div className="flex flex-col gap-1">
                  <span className="text-[10.5px] font-bold uppercase tracking-widest text-tx-muted">
                    Last reviewed
                  </span>
                  <span
                    className={cn(
                      "text-[14px] font-semibold",
                      !selected.lastReviewed ? "text-status-error" : "text-tx-primary",
                    )}
                  >
                    {selected.lastReviewed ?? "never"}
                  </span>
                </div>
              )}
            </div>

            {devFreshnessControls && (
              <p className="mt-4 rounded-md px-4 py-3 text-[12.5px] font-medium bg-brand-soft/40 border border-brand-border/40 text-tx-secondary shadow-sm">
                Development mode: staleness follows{" "}
                <span className="font-semibold text-tx-primary">
                  {selected.staleReferenceField === "lastReviewed"
                    ? "Last reviewed"
                    : "Effective"}
                </span>
                {selected.staleReferenceDate ? ` (${selected.staleReferenceDate})` : ""}. Edit
                those dates or use the quick actions below to simulate fresh vs past-review sheets.
              </p>
            )}

            {(selected.stale || selected.undated) && (
              <p className="mt-4 rounded-md px-4 py-3 text-[13px] font-medium bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
                {selected.undated
                  ? "No review or effective date on file, so staleness cannot be judged."
                  : `This sheet is ${selected.ageDays} days old (from ${selected.staleReferenceField ?? "effective"}). Quotes priced from it may be wrong.`}{" "}
                {selected.steward
                  ? `Steward: ${selected.steward}.`
                  : "No refresh owner has been assigned yet."}
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
                          className={cn(fieldClassName(), "tnum")}
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
                    className={cn(fieldClassName(), "tnum w-[120px]")}
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
                {uploading ? `Uploading ${uploading}…` : "Upload a newer sheet"}
              </button>
              <button
                onClick={requestSheet}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
              >
                <Envelope size={15} weight="duotone" />
                Request an updated sheet
              </button>
              {devFreshnessControls ? (
                <>
                  <button
                    type="button"
                    onClick={() => setFreshness("fresh")}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm disabled:opacity-60"
                  >
                    <CheckCircle size={15} weight="duotone" />
                    Mark fresh (dev)
                  </button>
                  <button
                    type="button"
                    onClick={() => setFreshness("stale")}
                    disabled={busy}
                    className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm disabled:opacity-60"
                  >
                    Mark stale (dev)
                  </button>
                </>
              ) : (
                <button
                  onClick={markReviewed}
                  className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
                >
                  <CheckCircle size={15} weight="duotone" />
                  Mark as reviewed today
                </button>
              )}
              <button
                onClick={downloadSheet}
                className="flex items-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
              >
                <DownloadSimple size={15} weight="duotone" />
                Download current sheet
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
                : "Changing the multiplier reprices every list-priced part on this program."}{" "}
              Uploading a sheet queues <span className="font-semibold">index_catalog</span> for
              page search
              {selected.kind === "multiplier_sheet"
                ? ""
                : ""}
              .
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
                        <span className="truncate text-[13px] font-semibold text-tx-primary">
                          {part.part}
                        </span>
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

            <div className="mt-10">
              <span className="mb-3 block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Version history
              </span>
              <div className="overflow-x-auto rounded-xl border border-subtle bg-background shadow-sm">
                <div
                  className="grid gap-4 border-b border-subtle bg-panel/50 px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest text-tx-muted"
                  style={{ minWidth: 620, gridTemplateColumns: "minmax(160px,1fr) 170px 210px 96px" }}
                >
                  <span>Sheet</span>
                  <span>Effective</span>
                  <span>Uploaded</span>
                  <span className="text-right">State</span>
                </div>
                <div className="divide-y divide-subtle">
                  {/* Newest first: the sheet in force, then whatever it replaced. */}
                  {[
                    {
                      filename: selected.filename,
                      effective: selected.effective,
                      uploadedAt: selected.uploadedAt,
                      state: "In force",
                      tone: "text-status-success",
                    },
                    ...[...(selected.sheetHistory ?? [])].reverse().map((sheet, index) => ({
                      filename: sheet.filename,
                      effective: sheet.effective,
                      uploadedAt: sheet.uploadedAt,
                      state: index === 0 ? "Superseded" : "Archived",
                      tone: "text-tx-muted",
                    })),
                  ].map((row, index) => (
                    <div
                      key={`${row.filename ?? "none"}-${index}`}
                      className="grid items-center gap-4 px-4 py-3"
                      style={{ minWidth: 620, gridTemplateColumns: "minmax(160px,1fr) 170px 210px 96px" }}
                    >
                      <span className="truncate text-[12.5px] font-semibold text-tx-primary">
                        {row.filename ?? "No file uploaded"}
                      </span>
                      <span className="tnum text-[12.5px] font-medium text-tx-secondary">
                        {row.effective ?? "—"}
                      </span>
                      <span className="tnum text-[12.5px] font-medium text-tx-muted">
                        {row.uploadedAt ? new Date(row.uploadedAt).toLocaleString() : "—"}
                      </span>
                      <span className={cn("text-right text-[12px] font-bold", row.tone)}>
                        {row.state}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
              <p className="mt-2 text-[11.5px] font-medium leading-relaxed text-tx-muted">
                A new sheet supersedes the one in force; the file it replaced stays on disk so any
                quote priced from it can still be reconstructed.
              </p>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
