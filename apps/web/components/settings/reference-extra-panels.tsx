"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import {
  Books,
  Cube,
  GridFour,
  Package,
  Table,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type {
  CustomOtherMatrix,
  LiteKitResponse,
  SpecialNetsDoc,
  StockListDoc,
  VendorTierDoc,
  VendorTierRow,
} from "@/lib/types";

const inputClass =
  "rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border transition-colors shadow-sm w-full font-mono";

/** Vendor category multipliers (Mongo vendor_tiers). */
export function VendorTiersPanel() {
  const { data, error, isLoading, mutate } = useSWR<VendorTierDoc>(
    "/api/proxy/reference/vendor-tiers",
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [vendor, setVendor] = useState("hager");

  const selected = useMemo(
    () =>
      data?.vendors?.find(
        (v: VendorTierRow) => v.key === vendor || v.name?.toLowerCase() === vendor,
      ),
    [data, vendor],
  );

  async function saveCategories(raw: string) {
    let categories: Record<string, number>;
    try {
      categories = JSON.parse(raw) as Record<string, number>;
    } catch {
      toast.error("Categories must be valid JSON object of name → multiplier");
      return;
    }
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/reference/vendor-tiers", {
        method: "PATCH",
        body: { vendor, categories },
      });
      toast.success(`Updated categories for ${vendor}`);
      mutate();
    } catch (problem) {
      toast.error("Could not save vendor tiers", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Books size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Vendor tiers</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Category multipliers purchasing maintains. Stored in Mongo referenceData.
        </p>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-4 flex flex-col gap-3">
          <label className="text-[12px] font-semibold text-tx-secondary">
            Vendor
            <select
              className={`${inputClass} mt-1`}
              value={vendor}
              onChange={(e) => setVendor(e.target.value)}
              disabled={busy}
            >
              {(data.vendors ?? []).map((v: VendorTierRow) => (
                <option key={v.key} value={v.key}>
                  {v.name || v.key}
                </option>
              ))}
            </select>
          </label>
          <label className="text-[12px] font-semibold text-tx-secondary">
            Categories JSON
            <textarea
              key={vendor + JSON.stringify(selected?.categories ?? {})}
              className={`${inputClass} mt-1 min-h-[140px]`}
              defaultValue={JSON.stringify(selected?.categories ?? {}, null, 2)}
              disabled={busy}
              onBlur={(e) => {
                const next = e.target.value.trim();
                const prev = JSON.stringify(selected?.categories ?? {}, null, 2);
                if (next !== prev) saveCategories(next);
              }}
            />
          </label>
        </div>
      )}
    </section>
  );
}

/** Hager special nets list. */
export function SpecialNetsPanel() {
  const { data, error, isLoading, mutate } = useSWR<SpecialNetsDoc>(
    "/api/proxy/reference/special-nets",
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState({ part_number: "", net_price: "" });

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/reference/special-nets", { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save special net", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full max-h-[480px]">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Package size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Hager special nets</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Fixed net overrides from the multiplier sheet.
        </p>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-3 overflow-auto flex-1">
          <form
            className="flex gap-2 mb-3"
            onSubmit={(e) => {
              e.preventDefault();
              const part = draft.part_number.trim();
              const net = Number(draft.net_price);
              if (!part || Number.isNaN(net)) {
                toast.error("Part number and net price required");
                return;
              }
              save({ items: [{ part_number: part, net_price: net }] }, `${part} saved`);
              setDraft({ part_number: "", net_price: "" });
            }}
          >
            <input
              className={inputClass}
              placeholder="Part"
              value={draft.part_number}
              onChange={(e) => setDraft((d) => ({ ...d, part_number: e.target.value }))}
              disabled={busy}
            />
            <input
              className={inputClass}
              placeholder="Net $"
              value={draft.net_price}
              onChange={(e) => setDraft((d) => ({ ...d, net_price: e.target.value }))}
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md px-3 py-2 text-[13px] font-semibold bg-brand-primary text-white shrink-0"
            >
              Add
            </button>
          </form>
          <ul className="text-[13px] space-y-1">
            {(data.items ?? []).slice(0, 40).map((item) => (
              <li key={item.part_number} className="flex justify-between gap-2 border-b border-subtle py-1">
                <span className="font-mono">{item.part_number}</span>
                <span>${Number(item.net_price).toFixed(2)}</span>
                <button
                  type="button"
                  className="text-status-error text-[12px]"
                  disabled={busy}
                  onClick={() => save({ remove: [item.part_number] }, `${item.part_number} removed`)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
          {(data.items?.length ?? 0) > 40 && (
            <p className="text-[12px] text-tx-muted mt-2">Showing first 40 of {data.items?.length}</p>
          )}
        </div>
      )}
    </section>
  );
}

/** Lite-kit table picker + JSON editor for selected table document. */
export function LiteKitPanel() {
  const { data, error, isLoading, mutate } = useSWR<LiteKitResponse>(
    "/api/proxy/reference/lite-kit",
    proxyFetcher,
  );
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);

  async function saveFull(raw: string) {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      toast.error("Lite-kit document must be valid JSON");
      return;
    }
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/reference/lite-kit", { method: "PUT", body: { data: parsed } });
      toast.success("Lite-kit prices saved");
      mutate();
    } catch (problem) {
      toast.error("Could not save lite-kit", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Table size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Lite-kit prices</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          NGP width × height tables. Edit the full document as JSON (v1).
        </p>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-4 flex flex-col gap-3">
          <p className="text-[12px] text-tx-secondary">{data.tableCount} tables on file</p>
          <select
            className={inputClass}
            value={index}
            onChange={(e) => setIndex(Number(e.target.value))}
          >
            {(data.tables ?? []).map((t) => (
              <option key={t.index} value={t.index}>
                #{t.index} page {t.pdf_page ?? "?"} — {t.title || "table"} ({t.widthCount}×
                {t.heightCount})
              </option>
            ))}
          </select>
          <textarea
            key={String(data.tableCount)}
            className={`${inputClass} min-h-[180px] text-[11px]`}
            defaultValue={JSON.stringify(data.data ?? {}, null, 2)}
            disabled={busy}
            onBlur={(e) => {
              const next = e.target.value.trim();
              const prev = JSON.stringify(data.data ?? {}, null, 2);
              if (next !== prev) saveFull(next);
            }}
          />
        </div>
      )}
    </section>
  );
}

function StockVendorPanel({ vendor, title }: { vendor: string; title: string }) {
  const { data, error, isLoading, mutate } = useSWR<StockListDoc>(
    `/api/proxy/reference/stock/${vendor}`,
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);
  const [part, setPart] = useState("");

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/reference/stock/${vendor}`, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save stock list", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full max-h-[420px]">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Cube size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">{title}</h2>
        </div>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-3 overflow-auto flex-1">
          <form
            className="flex gap-2 mb-3"
            onSubmit={(e) => {
              e.preventDefault();
              const p = part.trim();
              if (!p) return;
              save({ items: [{ part_number: p }] }, `${p} added`);
              setPart("");
            }}
          >
            <input
              className={inputClass}
              placeholder="Part number"
              value={part}
              onChange={(e) => setPart(e.target.value)}
              disabled={busy}
            />
            <button
              type="submit"
              disabled={busy}
              className="rounded-md px-3 py-2 text-[13px] font-semibold bg-brand-primary text-white shrink-0"
            >
              Add
            </button>
          </form>
          <ul className="text-[13px] space-y-1">
            {(data.items ?? []).map((item) => (
              <li key={item.part_number} className="flex justify-between border-b border-subtle py-1">
                <span className="font-mono">{item.part_number}</span>
                <button
                  type="button"
                  className="text-status-error text-[12px]"
                  disabled={busy}
                  onClick={() => save({ remove: [item.part_number] }, `${item.part_number} removed`)}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

export function StockListsPanel() {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <StockVendorPanel vendor="hager" title="Hager top-10 stock" />
      <StockVendorPanel vendor="allegion" title="Allegion stock" />
    </div>
  );
}

export function CustomOtherMatrixPanel() {
  const { data, error, isLoading, mutate } = useSWR<CustomOtherMatrix>(
    "/api/proxy/reference/custom-other-matrix",
    proxyFetcher,
  );
  const [busy, setBusy] = useState(false);

  async function save(raw: string) {
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      toast.error("Matrix must be valid JSON");
      return;
    }
    setBusy(true);
    try {
      await proxyMutate("/api/proxy/reference/custom-other-matrix", {
        method: "PUT",
        body: { data: parsed },
      });
      toast.success("Custom/OTHER matrix saved");
      mutate();
    } catch (problem) {
      toast.error("Could not save matrix", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <GridFour size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Custom / OTHER matrix</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Hardware-set matrix for custom openings. Edit as JSON.
        </p>
      </div>
      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">{errorMessage(error)}</p>
      )}
      {isLoading && !data && <p className="px-5 py-6 text-[13px] text-tx-muted">Loading…</p>}
      {data && (
        <div className="px-5 py-4">
          <textarea
            className={`${inputClass} min-h-[200px] text-[11px]`}
            defaultValue={JSON.stringify(data, null, 2)}
            disabled={busy}
            onBlur={(e) => {
              const next = e.target.value.trim();
              const prev = JSON.stringify(data, null, 2);
              if (next !== prev) save(next);
            }}
          />
        </div>
      )}
    </section>
  );
}
