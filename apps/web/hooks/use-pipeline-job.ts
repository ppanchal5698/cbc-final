"use client";

import useSWR from "swr";

import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { Job } from "@/lib/types";

const PIPELINE_TYPES = new Set([
  "extract_bid_set",
  "rerun_extraction",
  "match_and_price",
  "build_proposal",
  "ingest_addendum",
  "run_full_pipeline",
]);

export function isPipelineJob(job: Job | null | undefined): boolean {
  return Boolean(job && PIPELINE_TYPES.has(job.type));
}

/** Active queued/running pipeline job for this bid, if any. */
export function usePipelineJob(code: string, initialJob?: Job | null) {
  const { data, error, mutate } = useSWR<{ jobs: Job[] }>(
    `/api/proxy/jobs?project=${encodeURIComponent(code)}&pipeline_active=true`,
    proxyFetcher,
    {
      refreshInterval: (latest) => {
        const current = latest?.jobs?.[0] ?? initialJob;
        return current?.status === "running" || current?.status === "queued" ? 4000 : 0;
      },
      fallbackData:
        initialJob && isPipelineJob(initialJob) ? { jobs: [initialJob] } : undefined,
    },
  );

  const job = data?.jobs?.[0] ?? null;
  const running = job?.status === "running" || job?.status === "queued";

  return { job, running, error, mutate };
}
