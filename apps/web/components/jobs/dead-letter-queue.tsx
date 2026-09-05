"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import type { Job } from "@/lib/types";
import { endpoints } from "@/lib/endpoints";
import { errorMessage, proxyMutate } from "@/lib/proxy-fetcher";
import { jobTypeLabel } from "@/lib/job-error";

export function DeadLetterQueue({
  initialJobs,
}: {
  initialJobs: Job[];
}) {
  const router = useRouter();
  const [jobs, setJobs] = useState(initialJobs);
  const [busy, setBusy] = useState<string | null>(null);

  async function retry(job: Job) {
    setBusy(job.id);
    try {
      await proxyMutate(endpoints.jobRetry(job.id), { method: "POST" });
      setJobs((current) => current.filter((row) => row.id !== job.id));
      toast.success(`Requeued ${jobTypeLabel(job.type)}`);
      router.refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  if (jobs.length === 0) {
    return (
      <p className="rounded-xl border border-subtle bg-panel px-5 py-8 text-[14px] text-tx-secondary">
        No dead-lettered jobs. Exhausted or permanently failed runs will land here.
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-subtle bg-panel shadow-sm">
      <table className="w-full border-collapse text-left text-[13px]">
        <thead className="border-b border-subtle bg-panel-muted text-[11px] font-bold uppercase tracking-widest text-tx-muted">
          <tr>
            <th className="px-4 py-3">Bid</th>
            <th className="px-4 py-3">Job</th>
            <th className="px-4 py-3">Error</th>
            <th className="px-4 py-3">Trace</th>
            <th className="px-4 py-3">Finished</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody>
          {jobs.map((job) => (
            <tr key={job.id} className="border-b border-subtle last:border-0">
              <td className="px-4 py-3 font-semibold text-tx-primary">
                {job.projectCode ? (
                  <Link
                    href={`/bids/${job.projectCode}/intake`}
                    className="text-brand-primary no-underline hover:underline"
                  >
                    {job.projectCode}
                  </Link>
                ) : (
                  "—"
                )}
                {job.projectName ? (
                  <div className="mt-0.5 text-[12px] font-medium text-tx-muted">
                    {job.projectName}
                  </div>
                ) : null}
              </td>
              <td className="px-4 py-3 text-tx-secondary">{jobTypeLabel(job.type)}</td>
              <td className="max-w-[28rem] px-4 py-3 font-medium text-status-error">
                {job.error || "Unknown failure"}
              </td>
              <td className="max-w-[12rem] px-4 py-3">
                {job.traceId ? (
                  <button
                    type="button"
                    title="Copy trace id"
                    onClick={() => {
                      void navigator.clipboard.writeText(job.traceId!);
                      toast.success("Trace id copied");
                    }}
                    className="truncate font-mono text-[11px] text-tx-muted hover:text-tx-primary"
                  >
                    {job.traceId}
                  </button>
                ) : (
                  <span className="text-tx-muted">—</span>
                )}
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-tx-muted">
                {job.finishedAt ? new Date(job.finishedAt).toLocaleString() : "—"}
              </td>
              <td className="px-4 py-3 text-right">
                <button
                  type="button"
                  disabled={busy === job.id}
                  onClick={() => void retry(job)}
                  className="rounded-lg border border-brand-border bg-brand-soft px-3 py-1.5 text-[12.5px] font-bold text-brand-primary hover:bg-brand-soft/80 disabled:opacity-50"
                >
                  {busy === job.id ? "Retrying…" : "Retry"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
