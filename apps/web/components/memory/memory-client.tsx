"use client";

import { useState, type ReactNode } from "react";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowsClockwise } from "@phosphor-icons/react/dist/ssr";

import { FetchError } from "@/components/ui/fetch-error";
import { endpoints } from "@/lib/endpoints";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { MemoryFinding, MemorySummary } from "@/lib/types";
import { formatMoneyShort } from "@/lib/format";

// What the graph holds, in the order an estimator thinks about it. Every other
// label it holds is listed under "Also connected".
const PRIMARY: { label: string; nodes: string[]; hint: string }[] = [
  { label: "Vendors", nodes: ["Vendor"], hint: "Every vendor a tier, price book or catalog row names" },
  { label: "Multipliers", nodes: ["Multiplier"], hint: "Per vendor, per product category" },
  { label: "Customers", nodes: ["Customer"], hint: "Brands, GCs and special-margin accounts" },
  { label: "Catalog items", nodes: ["CatalogItem"], hint: "Linked to vendor, price book, section and multiplier" },
  { label: "Divisions", nodes: ["Division"], hint: "MasterFormat divisions; each part linked to its section" },
  { label: "Reference data", nodes: ["ReferenceFamily"], hint: "Each reference family, its entries linked" },
  { label: "Frame depths", nodes: ["FrameDepth"], hint: "Wall type to frame depth" },
  { label: "FRP constants", nodes: ["FrpConstant"], hint: "Geometry-to-quantity conversion" },
  { label: "Successful bids", nodes: ["Bid"], hint: "Approved bids and the workflow behind each" },
];
const SHOWN = new Set(PRIMARY.flatMap((p) => p.nodes));

function when(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "never";
}

const SEVERITY: Record<MemoryFinding["severity"], string> = {
  high: "bg-status-error-soft text-status-error border-status-error/30",
  medium: "bg-status-warning-soft text-status-warning border-status-warning/30",
  low: "bg-panel-muted text-tx-muted border-subtle",
};
const WHO_FIXES: Record<NonNullable<MemoryFinding["whoFixes"]>, string> = {
  purchasing: "Purchasing",
  estimating: "Estimating",
  admin: "An admin, in Reference data",
  it: "IT",
};

const sectionClass = "rounded-xl bg-panel border border-subtle shadow-sm";
const emptyClass = "rounded-lg border border-subtle bg-panel-muted px-4 py-3 text-[13px] font-medium text-tx-muted";

function SectionHeader({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border-b border-subtle px-5 py-4">
      <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">{title}</h2>
      <p className="mt-1 text-[13px] font-medium text-tx-secondary">{children}</p>
    </div>
  );
}

export function MemoryClient() {
  const { data, error, isLoading, mutate } = useSWR<MemorySummary>(endpoints.memory(), proxyFetcher, {
    refreshInterval: 30_000,
    keepPreviousData: true,
  });
  const [syncing, setSyncing] = useState(false);
  const [dismissing, setDismissing] = useState<string | null>(null);

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

  async function dismiss(finding: MemoryFinding) {
    const note = window.prompt(
      `Dismiss "${finding.headline ?? finding.summary}"?\n\nWhy is it not a problem? (optional)`,
      "",
    );
    if (note === null) return;
    setDismissing(finding.key);
    try {
      await proxyMutate(endpoints.memoryDismiss(), { method: "POST", body: { key: finding.key, note: note.trim() || null } });
      toast.success("Dismissed. It stays dismissed while the steward keeps seeing it.");
      mutate();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDismissing(null);
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
              Three agents keep it on their own. The curator syncs every few hours (last {when(data?.lastSyncAt)})
              and learns a bid the moment its proposal is approved. After each, the steward checks the graph for
              problems (last {when(data?.agents?.steward?.lastRunAt)}) and the historian records what each
              customer&apos;s bids show (last {when(data?.agents?.historian?.lastRunAt)}).
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
        <section className={sectionClass}>
          <SectionHeader title="Findings">
            What the steward found wrong in the graph, worst first. Each check is code; the explanation under it is the
            model putting the same facts in words. A finding closes itself once its source is fixed.
          </SectionHeader>
          <div className="px-5 py-4">
            {(data.findings ?? []).length === 0 ? (
              <p className={emptyClass}>Nothing wrong found on the last check.</p>
            ) : (
              <ul className="flex flex-col gap-3">
                {(data.findings ?? []).map((f) => (
                  <li
                    key={f.key}
                    className={`rounded-lg border border-subtle bg-background p-3 shadow-sm ${f.status === "dismissed" ? "opacity-60" : ""}`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0 text-[13px]">
                        <span
                          className={`inline-block rounded-full border px-2 py-0.5 text-[10.5px] font-bold uppercase tracking-widest ${SEVERITY[f.severity]}`}
                        >
                          {f.status === "dismissed" ? "dismissed" : f.severity}
                        </span>
                        <p className="mt-1.5 font-semibold text-tx-primary">{f.headline ?? f.summary}</p>
                        {f.headline && <p className="mt-1 font-medium text-tx-secondary">{f.summary}</p>}
                        {f.whyItMatters && (
                          <p className="mt-1.5 text-tx-secondary">
                            <span className="font-semibold text-tx-primary">Why it matters: </span>
                            {f.whyItMatters}
                          </p>
                        )}
                        {f.suggestedFix && (
                          <p className="mt-1 text-tx-secondary">
                            <span className="font-semibold text-tx-primary">Fix: </span>
                            {f.suggestedFix}
                            {f.whoFixes && <span className="text-tx-muted"> — {WHO_FIXES[f.whoFixes]}</span>}
                          </p>
                        )}
                        {f.status === "dismissed" && (
                          <p className="mt-1 text-[12px] text-tx-muted">
                            Dismissed by {f.dismissedBy}
                            {f.dismissNote ? `: ${f.dismissNote}` : ""}
                          </p>
                        )}
                      </div>
                      {f.status === "open" && (
                        <button
                          type="button"
                          onClick={() => dismiss(f)}
                          disabled={dismissing === f.key}
                          className="shrink-0 rounded-md border border-subtle px-2.5 py-1 text-[12px] font-medium text-tx-secondary hover:bg-panel-muted disabled:opacity-60"
                        >
                          {dismissing === f.key ? "Dismissing…" : "Dismiss"}
                        </button>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      )}

      {data?.available && (
        <section className={sectionClass}>
          <SectionHeader title="What customers' bids show">
            Written by the historian from approved bids only: what each brand and GC was sold, and the margin CBC bid
            per section. The next bid for that customer is given this as context, never as a value.
          </SectionHeader>
          <div className="px-5 py-4">
            {(data.insights ?? []).length === 0 ? (
              <p className={emptyClass}>
                Nothing yet. After the first approved bid, the historian writes what each customer&apos;s bids show.
              </p>
            ) : (
              <div className="grid gap-3 lg:grid-cols-2">
                {(data.insights ?? []).map((insight) => (
                  <div key={insight.customer} className="rounded-lg border border-subtle bg-background p-3 text-[13px] shadow-sm">
                    <p className="font-bold text-tx-primary">
                      {insight.customer}
                      <span className="font-medium text-tx-muted"> · {insight.bids} approved bid{insight.bids === 1 ? "" : "s"}</span>
                    </p>
                    <p className="mt-1 text-tx-secondary">{insight.summary}</p>
                    {(insight.patterns ?? []).length > 0 && (
                      <ul className="mt-1.5 list-disc pl-5 text-tx-secondary">
                        {(insight.patterns ?? []).map((p) => (
                          <li key={p}>{p}</li>
                        ))}
                      </ul>
                    )}
                    {(insight.cautions ?? []).map((c) => (
                      <p key={c} className="mt-1 text-status-warning">Check: {c}</p>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      {data?.available && (
        <section className={sectionClass}>
          <SectionHeader title="Recently learned bids">
            Each one approved by an estimator: who it was for, its sets, what every line was priced as, and how the
            pipeline got there. The next bid for the same brand or GC starts from these.
          </SectionHeader>
          <div className="px-5 py-4">
            {(data.recentBids ?? []).length === 0 ? (
              <p className={emptyClass}>
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
