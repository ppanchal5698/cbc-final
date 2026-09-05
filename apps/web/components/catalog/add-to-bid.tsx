"use client";

import { useState } from "react";
import useSWR from "swr";
import { Plus } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import type { LineItem, Product, Project } from "@/lib/types";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { FetchError } from "@/components/ui/fetch-error";

/**
 * Put a catalog part straight onto an open bid.
 *
 * The other direction of the extraction screen's composer: there, you search the
 * catalog from the bid; here, you pick the bid from the catalog. Both land the
 * same way - a by-hand line, already confirmed, because a human chose it.
 */
export function AddToBid({ product }: { product: Product }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const { data, error, isLoading, mutate } = useSWR<{ projects: Project[] }>(
    open ? "/api/proxy/projects?limit=50" : null,
    proxyFetcher,
  );

  // A finished bid is the wrong place to drop a new line.
  const candidates = (data?.projects ?? []).filter((p) => p.stage !== "proposal");

  async function add(project: Project) {
    setBusy(true);
    try {
      await proxyMutate<LineItem>(`/api/proxy/projects/${project.code}/line-items`, {
        body: {
          description: product.description,
          part: product.part,
          division: product.division,
          qty: 1,
        },
      });
      toast.success(`${product.part} added to ${project.code}`, {
        description: "Marked as added by hand, and already confirmed.",
      });
      setOpen(false);
    } catch (problem) {
      toast.error("Could not add it", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-6 flex w-full items-center justify-center gap-1.5 rounded-md py-2.5 text-[13px] font-semibold bg-brand-soft border border-brand-border text-brand-primary shadow-sm hover:bg-brand-soft/80 transition-colors"
      >
        <Plus size={16} weight="bold" />
        Add to a bid by hand
      </button>
    );
  }

  return (
    <div className="animate-fade-in mt-6 rounded-lg p-4 bg-panel border border-subtle shadow-sm">
      <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-3">
        Add to which bid?
      </span>

      {!data && !error && isLoading ? (
        <p className="mt-2 text-[12.5px] font-medium text-tx-muted">
          Loading bids…
        </p>
      ) : error ? (
        <FetchError
          title="Could not load bids"
          error={error}
          onRetry={() => mutate()}
          compact
        />
      ) : candidates.length === 0 ? (
        <p className="mt-2 text-[12.5px] font-medium text-tx-secondary">
          No open bids to add to. Bids at the proposal stage are excluded.
        </p>
      ) : (
        <div className="mt-2 flex flex-col gap-1 max-h-48 overflow-y-auto pr-1">
          {candidates.map((project) => (
            <button
              key={project.id}
              onClick={() => add(project)}
              disabled={busy}
              className="flex items-center gap-2.5 rounded-md px-3 py-2.5 text-left text-[13px] disabled:opacity-50 hover:bg-panel-muted transition-colors"
            >
              <span className="tnum font-bold text-brand-primary">
                {project.code}
              </span>
              <span className="min-w-0 flex-1 truncate font-medium text-tx-secondary">
                {project.name}
              </span>
              <span className="text-[11.5px] font-medium text-tx-muted uppercase tracking-widest">
                {project.stage}
              </span>
            </button>
          ))}
        </div>
      )}

      <button
        onClick={() => setOpen(false)}
        className="mt-3 w-full rounded-md py-2 text-[12.5px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors"
      >
        Cancel
      </button>
    </div>
  );
}
