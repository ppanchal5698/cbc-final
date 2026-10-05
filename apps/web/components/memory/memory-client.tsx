"use client";

import { useState } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowsClockwise } from "@phosphor-icons/react/dist/ssr";

import { FetchError } from "@/components/ui/fetch-error";
import { endpoints } from "@/lib/endpoints";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { MemorySummary } from "@/lib/types";
import { formatMoneyShort } from "@/lib/format";

// What the graph holds, in the order an estimator thinks about it. Every other
// label it holds is listed under "Also connected".
const PRIMARY: { label: string; nodes: string[]; hint: string }[] = [
  { label: "Vendors", nodes: ["Vendor"], hint: "Every vendor a tier, price book or catalog row names" },
  { label: "Multipliers", nodes: ["Multiplier"], hint: "Per vendor, per product category" },
  { label: "Customers", nodes: ["Customer"], hint: "Brands, GCs and special-margin accounts" },
  { label: "Catalog items", nodes: ["CatalogItem"], hint: "Linked to their vendor and price book" },
  { label: "Reference data", nodes: ["ReferenceFamily"], hint: "Each reference family, its entries linked" },
  { label: "Frame depths", nodes: ["FrameDepth"], hint: "Wall type to frame depth" },
  { label: "FRP constants", nodes: ["FrpConstant"], hint: "Geometry-to-quantity conversion" },
  { label: "Successful bids", nodes: ["Bid"], hint: "Approved bids and the workflow behind each" },
];
const SHOWN = new Set(PRIMARY.flatMap((p) => p.nodes));

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "never";
}

export function MemoryClient() {
  const { data, error, isLoading, mutate } = useSWR<MemorySummary>(endpoints.memory(), proxyFetcher, {
    refreshInterval: 30_000,
    keepPreviousData: true,
  });
  const [syncing, setSyncing] = useState(false);

  async function syncNow() {
    setSyncing(true);
    try {
      await proxyMutate(endpoints.memorySync(), { method: "POST" });
      toast.success("Sync queued. The counts refresh when it finishes.");
      setTimeout(() => mutate(), 5_000);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSyncing(false);
    }
  }

  const nodes = data?.nodes ?? {};
  const others = Object.entries(nodes).filter(([label]) => !SHOWN.has(label));
  const relationships = Object.entries(data?.relationships ?? {}).sort((a, b) => b[1] - a[1]);

  return (
    <div className="flex flex-col gap-4">
      <section className="rounded-xl bg-panel border border-subtle shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-4 border-b border-subtle px-5 py-4">
          <div>
            <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">What the memory holds</h2>
            <p className="mt-1 text-[13px] font-medium text-tx-secondary">
              Last sync {when(data?.lastSyncAt)}. The curator syncs on its own every few hours and learns a bid the
              moment its proposal is approved.
            </p>
          </div>
          <button
            type="button"
            onClick={syncNow}
            disabled={syncing || !data?.configured}
            className="flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground disabled:opacity-60"
          >
            <ArrowsClockwise size={14} weight="bold" />
            {syncing ? "Queuing…" : "Sync now"}
          </button>
        </div>

        <div className="px-5 py-4">
          {error && <FetchError title="Could not read the memory graph" error={error} onRetry={() => mutate()} />}
          {isLoading && !data && <p className="text-[13px] font-medium text-tx-muted">Reading the graph…</p>}
          {data && !data.available && (
            <p className="rounded-lg border border-status-warning/30 bg-status-warning-soft px-4 py-3 text-[13px] font-medium text-status-warning">
              {data.configured
                ? "The memory graph is not reachable right now. Bids run as usual; the curator catches up when Neo4j is back."
                : "The memory graph is not configured (NEO4J_URI is empty). Bids run as usual without it."}
            </p>
          )}
          {data?.available && (
            <>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
                {PRIMARY.map(({ label, nodes: labels, hint }) => (
                  <div key={label} className="bg-background rounded-lg border border-subtle p-3 shadow-sm">
                    <p className="text-[12px] font-bold uppercase tracking-widest text-tx-muted mb-1">{label}</p>
                    <p className="tnum text-[22px] font-bold tracking-tight text-tx-primary">
                      {labels.reduce((sum, l) => sum + (nodes[l] ?? 0), 0).toLocaleString()}
                    </p>
                    <p className="mt-1 text-[11.5px] font-medium text-tx-muted">{hint}</p>
                  </div>
                ))}
              </div>
              {others.length > 0 && (
                <p className="mt-4 text-[12.5px] font-medium text-tx-secondary">
                  Also connected:{" "}
                  {others.map(([label, count]) => `${label.replace(/([a-z])([A-Z])/g, "$1 $2")} ${count}`).join(" · ")}
                </p>
              )}
              {relationships.length > 0 && (
                <p className="mt-2 text-[12.5px] font-medium text-tx-muted">
                  Relationships: {relationships.map(([type, count]) => `${type} ${count}`).join(" · ")}
                </p>
              )}
            </>
          )}
        </div>
      </section>

      {data?.available && (
        <section className="rounded-xl bg-panel border border-subtle shadow-sm">
          <div className="border-b border-subtle px-5 py-4">
            <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Recently learned bids</h2>
            <p className="mt-1 text-[13px] font-medium text-tx-secondary">
              Each one approved by an estimator: who it was for, its sets, what every line was priced as, and how the
              pipeline got there. The next bid for the same brand or GC starts from these.
            </p>
          </div>
          <div className="px-5 py-4">
            {(data.recentBids ?? []).length === 0 ? (
              <p className="rounded-lg border border-subtle bg-panel-muted px-4 py-3 text-[13px] font-medium text-tx-muted">
                Nothing learned yet. The first bid whose proposal an estimator approves appears here.
              </p>
            ) : (
              <div className="border border-subtle rounded-xl overflow-hidden shadow-sm">
                <table className="w-full text-[13px]">
                  <thead className="bg-panel-muted border-b border-subtle">
                    <tr>
                      {["Bid", "Brand", "GC", "Sets", "Lines", "Total", "Approved"].map((h) => (
                        <th key={h} className="px-4 py-2 text-left font-bold uppercase tracking-widest text-tx-muted text-[11px]">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-subtle bg-background">
                    {(data.recentBids ?? []).map((bid) => (
                      <tr key={bid.code} className="hover:bg-panel-muted transition-colors">
                        <td className="px-4 py-2.5 font-medium text-tx-primary">
                          {bid.code}
                          <span className="block text-[11.5px] text-tx-muted">{bid.name}</span>
                        </td>
                        <td className="px-4 py-2.5 text-tx-secondary">{bid.brand ?? "—"}</td>
                        <td className="px-4 py-2.5 text-tx-secondary">{bid.gc ?? "—"}</td>
                        <td className="tnum px-4 py-2.5 text-tx-secondary">{bid.sets}</td>
                        <td className="tnum px-4 py-2.5 text-tx-secondary">{bid.lines ?? "—"}</td>
                        <td className="tnum px-4 py-2.5 text-tx-secondary">
                          {bid.total != null ? formatMoneyShort(bid.total) : "—"}
                        </td>
                        <td className="px-4 py-2.5 text-tx-secondary">
                          {when(bid.approvedAt)}
                          <span className="block text-[11.5px] text-tx-muted">{bid.approvedBy}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  );
}
