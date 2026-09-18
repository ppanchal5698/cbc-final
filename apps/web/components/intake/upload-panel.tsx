"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Tray, FilePdf, UploadSimple, Trash } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import type { BidDocument, Job, UploadResult } from "@/lib/types";
import { FetchError } from "@/components/ui/fetch-error";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { waitingForSiblings } from "@/lib/run-pill";

const KINDS = [
  { key: "plan", label: "Plan set" },
  { key: "spec", label: "Specification" },
  { key: "rfp", label: "RFP" },
  { key: "addendum", label: "Addendum" },
] as const;

function parseStateLabel(document: BidDocument): {
  text: string;
  tone: "success" | "error" | "running" | "muted";
} {
  const parse = document.parse;
  if (!parse?.state) {
    return { text: "Not parsed — read directly", tone: "muted" };
  }
  if (parse.state === "queued") {
    return { text: "Queued for GPU", tone: "running" };
  }
  if (parse.state === "running") {
    const done = parse.pagesDone ?? 0;
    const total = parse.pages ?? document.pages ?? "?";
    const backend =
      typeof parse.settings?.backend === "string" ? parse.settings.backend : null;
    return {
      text: backend
        ? `Parsing ${done} / ${total} (${backend})`
        : `Parsing ${done} / ${total}`,
      tone: "running",
    };
  }
  if (parse.state === "parsed") {
    return { text: "Parsed", tone: "success" };
  }
  if (parse.state === "failed") {
    return { text: "Parse failed — read directly", tone: "error" };
  }
  return { text: "Not parsed — read directly", tone: "muted" };
}

export function UploadPanel({
  code,
  initialDocuments,
}: {
  code: string;
  initialDocuments: BidDocument[];
}) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [kind, setKind] = useState<string>("plan");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<{ name: string; index: number; total: number } | null>(
    null,
  );

  const { data, error: docsError, mutate } = useSWR<{ documents: BidDocument[] }>(
    `/api/proxy/projects/${code}/documents`,
    proxyFetcher,
    {
      fallbackData: { documents: initialDocuments },
      refreshInterval: (latest) => {
        const docs = latest?.documents ?? [];
        const parsing = docs.some(
          (doc) => doc.parse?.state === "queued" || doc.parse?.state === "running",
        );
        return parsing ? 4000 : 0;
      },
    },
  );
  const documents = data?.documents ?? [];

  const { data: jobData, error: jobsError } = useSWR<{ jobs: Job[] }>(
    `/api/proxy/jobs?project=${code}&limit=1`,
    proxyFetcher,
    {
      refreshInterval: (latest) => {
        const current = latest?.jobs?.[0];
        return current?.status === "running" || current?.status === "queued" ? 5000 : 0;
      },
    },
  );
  const job = jobData?.jobs?.[0];

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    const queue = Array.from(files);
    setBusy(true);

    for (const [index, file] of queue.entries()) {
      // Bid sets run to hundreds of megabytes; naming the file and its place in
      // the queue is the difference between "working" and "frozen".
      setProgress({ name: file.name, index: index + 1, total: queue.length });

      const form = new FormData();
      form.append("file", file);
      form.append("kind", kind);

      try {
        const result = await proxyMutate<UploadResult>(
          `/api/proxy/projects/${code}/documents`,
          { form },
        );
        toast.success(`${file.name} received`, {
          description:
            result.note ??
            (queue.length > 1
              ? `${result.document.pages ?? "?"} pages · extract waits briefly so sibling PDFs join the same run.`
              : `${result.document.pages ?? "?"} pages · Claude has been queued to read it.`),
        });
      } catch (problem) {
        toast.error(`${file.name} was not accepted`, { description: errorMessage(problem) });
      }
    }

    setProgress(null);
    setBusy(false);
    if (inputRef.current) inputRef.current.value = "";
    mutate();
    router.refresh();
  }

  async function remove(document: BidDocument) {
    if (
      !window.confirm(
        `Detach ${document.filename} from this bid? The file itself is kept — raw uploads are immutable.`,
      )
    ) {
      return;
    }
    try {
      await proxyMutate(`/api/proxy/projects/${code}/documents/${document.id}`, {
        method: "DELETE",
      });
      toast.success(`${document.filename} detached`, {
        description: "The file itself is kept — raw uploads are immutable.",
      });
      mutate();
      router.refresh();
    } catch (problem) {
      toast.error("Could not detach that document", { description: errorMessage(problem) });
    }
  }

  return (
    <div className="rounded-xl bg-panel border border-subtle shadow-sm">
      <div className="flex flex-wrap items-center gap-4 border-b border-subtle px-5 py-4">
        <span className="text-[16px] font-bold tracking-tight">Bid documents</span>
        <span className="text-[12.5px] font-medium text-tx-muted">
          {documents.length} file{documents.length === 1 ? "" : "s"}
          {jobsError ? " · job status unavailable" : ""}
          {!jobsError && (job?.status === "failed" || job?.status === "dead")
            ? " · last read failed — open the run for details"
            : ""}
          {!jobsError && job && waitingForSiblings(job) ? " · waiting for more files" : ""}
          {!jobsError && job?.stragglerPending && job.status === "running"
            ? " · late PDF will re-run after this pass"
            : ""}
          {!jobsError &&
          job &&
          (job.status === "running" || (job.status === "queued" && !waitingForSiblings(job)))
            ? " · Claude is reading"
            : ""}
        </span>
        <span className="flex-1" />
        <div className="flex flex-wrap gap-1.5">
          {KINDS.map((entry) => (
            <button
              key={entry.key}
              onClick={() => setKind(entry.key)}
              className={`rounded-lg px-3 py-1.5 text-[12px] font-bold transition-all shadow-sm ${
                kind === entry.key
                  ? "bg-brand-primary/10 text-brand-primary border border-brand-primary/20"
                  : "bg-background text-tx-secondary border border-subtle hover:bg-panel-muted hover:text-tx-primary"
              }`}
            >
              {entry.label}
            </button>
          ))}
        </div>
      </div>

      {docsError && (
        <FetchError
          title="Could not load documents"
          error={docsError}
          onRetry={() => mutate()}
          compact
        />
      )}

      {documents.length > 0 && (
        <div className="overflow-x-auto">
          <div
            className="grid gap-4 border-b border-subtle px-5 py-3 text-[11px] font-bold uppercase tracking-widest text-tx-muted bg-panel-muted"
            style={{
              minWidth: 640,
              gridTemplateColumns: "minmax(200px,1fr) 90px 110px minmax(160px,1.4fr) 40px",
            }}
          >
            <span>File</span>
            <span>Pages</span>
            <span>Received</span>
            <span>State</span>
            <span />
          </div>
          {documents.map((document) => {
            const parseLabel = parseStateLabel(document);
            return (
            <div
              key={document.id}
              className="grid items-center gap-4 border-b border-subtle px-5 py-3.5 last:border-b-0 hover:bg-background/50 transition-colors"
              style={{
                minWidth: 640,
                gridTemplateColumns: "minmax(200px,1fr) 90px 110px minmax(160px,1.4fr) 40px",
              }}
            >
              <span className="flex min-w-0 items-center gap-3">
                <FilePdf size={20} weight="duotone" className="text-cyan-500" />
                <span className="flex min-w-0 flex-col leading-tight gap-0.5">
                  <span className="truncate text-[13.5px] font-semibold text-tx-primary">{document.filename}</span>
                  <span className="text-[11.5px] font-medium text-tx-muted">
                    {document.kind}
                  </span>
                </span>
              </span>
              <span className="tnum text-[13px] font-medium text-tx-secondary">
                {document.pages ?? "—"}
              </span>
              <span className="text-[12.5px] font-medium text-tx-secondary">
                {new Date(document.uploadedAt).toLocaleDateString()}
              </span>
              <span
                className={`text-[12.5px] font-bold ${
                  parseLabel.tone === "success"
                    ? "text-status-success"
                    : parseLabel.tone === "error"
                      ? "text-status-error"
                      : parseLabel.tone === "running"
                        ? "text-brand-primary"
                        : "text-tx-secondary"
                }`}
                title={document.parse?.error ?? undefined}
              >
                {parseLabel.text}
              </span>
              <button
                onClick={() => remove(document)}
                aria-label={`Detach ${document.filename}`}
                className="text-tx-muted hover:text-status-error transition-colors p-1.5 rounded-md hover:bg-status-error-soft"
              >
                <Trash size={16} weight="fill" />
              </button>
            </div>
            );
          })}
        </div>
      )}

        <div
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setDragging(false);
            }
          }}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            upload(event.dataTransfer.files);
          }}
          className={`m-5 grid place-items-center gap-3 rounded-xl px-8 text-center transition-all ${
            documents.length > 0 ? "py-6" : "py-12"
          } ${
            dragging
              ? "border-2 border-dashed border-brand-primary bg-brand-primary/10"
              : "border-2 border-dashed border-subtle bg-background"
          }`}
        >
          <Tray size={32} weight="duotone" className="text-tx-muted" />
          <span className="text-[15px] font-bold text-tx-primary tracking-tight">
            {documents.length === 0 ? "No documents yet" : "Add another document"}
          </span>
          <span className="max-w-[460px] text-[13px] font-medium text-tx-secondary leading-relaxed">
            Drop one combined PDF or several separate PDFs (plans, specs, RFP). Multi-file
            uploads coalesce into one extract job after a short debounce so Claude sees the
            full set. Uploading is what notifies Claude — nothing else is needed.
          </span>

        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          multiple
          className="hidden"
          onChange={(event) => upload(event.target.files)}
        />
        <button
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="mt-2 flex items-center gap-2 rounded-lg px-5 py-2.5 text-[13px] font-bold disabled:opacity-50 transition-all bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
        >
          <UploadSimple size={16} weight="bold" />
          {busy ? "Uploading…" : "Choose PDFs"}
        </button>

        {progress && (
          <span
            className="mt-2 text-[12px] font-medium text-tx-secondary animate-pulse"
            aria-live="polite"
          >
            Sending {progress.name}
            {progress.total > 1 ? ` (${progress.index} of ${progress.total})` : ""}…
          </span>
        )}
      </div>
    </div>
  );
}
