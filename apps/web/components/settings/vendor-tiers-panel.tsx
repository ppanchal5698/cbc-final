"use client";

import { useMemo, useState } from "react";
import useSWR from "swr";
import { Books, Plus, Trash } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { VendorTierDoc, VendorTierRow } from "@/lib/types";

const URL = "/api/proxy/reference/vendor-tiers";

const inputClass =
  "tnum rounded-md px-3 py-1.5 text-right text-[13px] outline-none border border-subtle " +
  "bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm";

/** 0.29 reads as 71% off list, which is how purchasing states it. */
function asDiscount(multiplier: number): string {
  const off = (1 - multiplier) * 100;
  return `${off.toFixed(off % 1 === 0 ? 0 : 1)}% off list`;
}

function title(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Category multipliers, per vendor.
 *
 * This was a textarea holding the raw categories object as JSON. A typo produced
 * "must be valid JSON object" and lost the edit; a misplaced decimal produced a
 * silently wrong cost on every line that vendor touched. The numbers are now
 * edited one at a time and bounded on the way in, and the multiplier's account,
 * price book and effective date sit beside them - a cost that cannot name its
 * price-book version is not auditable (NFR-3).
 */
export function VendorTiersPanel() {
  const { data, error, isLoading, mutate } = useSWR<VendorTierDoc>(URL, proxyFetcher);
  const [busy, setBusy] = useState(false);
  const [picked, setVendorKey] = useState<string>("");
  const [draft, setDraft] = useState({ name: "", value: "" });
  const [bought, setBought] = useState({ name: "", via: "" });
  const [notQuoted, setNotQuoted] = useState({ name: "", reason: "" });

  const vendors = useMemo(() => data?.vendors ?? [], [data]);
  // Derived, not set in an effect: the first vendor until one is picked.
  const vendorKey = picked || vendors[0]?.key || "";

  const vendor: VendorTierRow | undefined = useMemo(
    () => vendors.find((v) => v.key === vendorKey),
    [vendors, vendorKey],
  );

  async function save(body: Record<string, unknown>, success: string) {
    setBusy(true);
    try {
      await proxyMutate(URL, { method: "PATCH", body });
      toast.success(success);
      mutate();
    } catch (problem) {
      toast.error("Could not save the vendor", { description: errorMessage(problem) });
      mutate();
    } finally {
      setBusy(false);
    }
  }

  function saveCategories(categories: Record<string, number>, success: string) {
    return save({ vendor: vendorKey, categories }, success);
  }

  /** "Banner Solutions, SecLock" -> both names; an empty box buys direct again. */
  function saveDistributors(name: string, raw: string, current: string[] = []) {
    const distributors = raw.split(",").map((d) => d.trim()).filter(Boolean);
    if (distributors.join(",") === current.join(",")) return;
    save(
      { vendor: name, distributors },
      distributors.length ? `${name} is bought through ${distributors.join(" / ")}` : `${name} is bought direct`,
    );
  }

  /** Requirements 1.2: vendors CBC does not quote; review flags any line from one. */
  function saveExcluded(next: Array<{ name: string; reason?: string | null }>, success: string) {
    save({ excluded: next.map(({ name, reason }) => ({ name, reason: reason || null })) }, success);
  }

  function addExcluded(event: React.FormEvent) {
    event.preventDefault();
    const name = notQuoted.name.trim();
    if (!name) {
      toast.error("Name the vendor CBC does not quote");
      return;
    }
    saveExcluded([...(data?.excluded ?? []), { name, reason: notQuoted.reason.trim() || null }], `${name} is not quoted`);
    setNotQuoted({ name: "", reason: "" });
  }

  function addDistributorVendor(event: React.FormEvent) {
    event.preventDefault();
    if (!bought.name.trim() || !bought.via.trim()) {
      toast.error("Name the vendor and who CBC buys it through");
      return;
    }
    saveDistributors(bought.name.trim(), bought.via);
    setBought({ name: "", via: "" });
  }

  function commit(name: string, raw: string, current: number) {
    const next = Number(raw);
    if (raw.trim() === "" || Number.isNaN(next) || next <= 0 || next > 1) {
      toast.error("A multiplier is a fraction of list: above 0, at most 1", {
        description: `e.g. 0.29 for 71% off. Got "${raw}".`,
      });
      mutate();
      return;
    }
    const rounded = Math.round(next * 10000) / 10000;
    if (rounded === current) return;
    saveCategories(
      { ...(vendor?.categories ?? {}), [name]: rounded },
      `${title(name)} set to ${rounded} (${asDiscount(rounded)})`,
    );
  }

  function remove(name: string) {
    if (!window.confirm(`Remove ${title(name)} from ${vendor?.name || vendorKey}?`)) return;
    const next = { ...(vendor?.categories ?? {}) };
    delete next[name];
    saveCategories(next, `${title(name)} removed`);
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const name = draft.name.trim().toLowerCase().replace(/\s+/g, "_");
    const value = Number(draft.value);
    if (!name) {
      toast.error("Name the product category");
      return;
    }
    if (vendor?.categories?.[name] !== undefined) {
      toast.error(`${title(name)} already exists`, { description: "Edit it in the list above." });
      return;
    }
    if (draft.value.trim() === "" || Number.isNaN(value) || value <= 0 || value > 1) {
      toast.error("A multiplier is a fraction of list: above 0, at most 1");
      return;
    }
    saveCategories({ ...(vendor?.categories ?? {}), [name]: value }, `${title(name)} added`);
    setDraft({ name: "", value: "" });
  }

  const categories = Object.entries(vendor?.categories ?? {}).sort(([a], [b]) => a.localeCompare(b));
  const facts: Array<[string, string | null | undefined]> = [
    ["Account", vendor?.account],
    ["Tier", vendor?.tier],
    ["Price book", vendor?.price_book],
    ["Effective", vendor?.effective_date],
  ];

  return (
    <section className="rounded-xl bg-panel border border-subtle shadow-sm flex flex-col h-full">
      <div className="border-b border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Books size={18} weight="bold" className="text-brand-primary" />
          <h2 className="text-[16px] font-bold text-tx-primary tracking-tight">Vendor tiers</h2>
        </div>
        <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
          Category multipliers purchasing maintains. A multiplier is the fraction of list CBC pays,
          so 0.29 is 71% off. Pricing re-reads these as soon as they change.
        </p>
      </div>

      {error && (
        <p className="px-5 py-6 text-[13px] font-medium text-status-error">
          Could not read the vendor tiers: {errorMessage(error)}
        </p>
      )}
      {isLoading && !data && (
        <p className="px-5 py-6 text-[13px] font-medium text-tx-muted">Loading…</p>
      )}

      {data && (
        <>
          <div className="border-b border-subtle px-5 py-3 flex flex-wrap items-end gap-5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Vendor
              </span>
              <select
                className="rounded-md px-3 py-2 text-[13px] font-medium outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
                value={vendorKey}
                onChange={(event) => setVendorKey(event.target.value)}
                disabled={busy}
                aria-label="Vendor"
              >
                {vendors.map((entry) => (
                  <option key={entry.key} value={entry.key}>
                    {entry.name || entry.key}
                  </option>
                ))}
              </select>
            </label>
            <dl className="flex flex-wrap gap-x-6 gap-y-1.5">
              {facts
                .filter(([, value]) => Boolean(value))
                .map(([label, value]) => (
                  <div key={label}>
                    <dt className="text-[10px] font-bold uppercase tracking-widest text-tx-muted">
                      {label}
                    </dt>
                    <dd className="text-[12.5px] font-medium text-tx-secondary">{value}</dd>
                  </div>
                ))}
            </dl>
          </div>

          {vendor?.note && (
            <p className="px-5 pt-3 text-[12.5px] font-medium text-tx-secondary">{vendor.note}</p>
          )}
          {vendor && (
            <label className="flex items-center gap-3 px-5 pt-3">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted shrink-0">
                Bought through
              </span>
              <input
                key={`${vendor.key}-${(vendor.distributors ?? []).join(",")}`}
                defaultValue={(vendor.distributors ?? []).join(", ")}
                placeholder="Direct - or name the distributors, comma separated"
                disabled={busy}
                aria-label={`Distributors for ${vendor.name || vendor.key}`}
                onBlur={(event) => saveDistributors(vendor.key, event.target.value, vendor.distributors)}
                className="flex-1 rounded-md px-3 py-1.5 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
          )}

          <div className="divide-y divide-subtle flex-1 overflow-y-auto">
            {categories.map(([name, value]) => (
              <div
                key={name}
                className="flex items-center gap-4 px-5 py-2.5 hover:bg-panel-muted transition-colors"
              >
                <span className="flex-1 text-[13.5px] font-semibold text-tx-primary">
                  {title(name)}
                </span>
                <span className="w-32 shrink-0 text-right text-[12px] font-medium text-tx-secondary">
                  {vendor?.discounts?.[name] || asDiscount(value)}
                </span>
                <input
                  key={`${name}-${value}`}
                  type="number"
                  step="0.0005"
                  min="0.0001"
                  max="1"
                  defaultValue={value}
                  disabled={busy}
                  aria-label={`${title(name)} multiplier`}
                  onBlur={(event) => commit(name, event.target.value, value)}
                  className={`${inputClass} w-24 shrink-0`}
                />
                <button
                  type="button"
                  onClick={() => remove(name)}
                  disabled={busy}
                  aria-label={`Remove ${title(name)}`}
                  className="shrink-0 rounded-md p-2 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors focus:ring-2 focus:ring-status-error"
                >
                  <Trash size={16} />
                </button>
              </div>
            ))}
            {categories.length === 0 && (
              <p className="px-5 py-4 text-[13px] font-medium text-tx-muted">
                {vendor?.multiplier
                  ? `No per-category rates — this vendor prices at a flat ${vendor.multiplier}.`
                  : "No category multipliers on file for this vendor."}
              </p>
            )}
          </div>

          <form
            onSubmit={add}
            className="flex items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4"
          >
            <label className="flex flex-col gap-1.5 flex-1">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Category
              </span>
              <input
                value={draft.name}
                onChange={(event) => setDraft((d) => ({ ...d, name: event.target.value }))}
                placeholder="exit_devices"
                aria-label="New product category"
                className="w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Multiplier
              </span>
              <input
                value={draft.value}
                onChange={(event) => setDraft((d) => ({ ...d, value: event.target.value }))}
                type="number"
                step="0.0005"
                min="0.0001"
                max="1"
                placeholder="0.30"
                aria-label="New category multiplier"
                className={`${inputClass} w-24`}
              />
            </label>
            <button
              type="submit"
              disabled={busy || !vendorKey}
              className="flex h-[38px] items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
            >
              <Plus size={16} weight="bold" />
              Add
            </button>
          </form>

          <div className="border-t border-subtle px-5 py-3">
            <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">Not quoted</span>
            <ul className="mt-1.5 space-y-1">
              {(data.excluded ?? []).map((entry) => (
                <li key={entry.name} className="flex items-center gap-3 text-[13px]">
                  <span className="font-semibold text-tx-primary">{entry.name}</span>
                  <span className="flex-1 truncate text-tx-secondary">{entry.reason}</span>
                  <button
                    type="button"
                    disabled={busy}
                    aria-label={`Quote ${entry.name} again`}
                    onClick={() =>
                      saveExcluded(
                        (data.excluded ?? []).filter((other) => other.name !== entry.name),
                        `${entry.name} is quoted again`,
                      )
                    }
                    className="shrink-0 rounded-md p-1.5 text-tx-muted hover:text-status-error hover:bg-status-error-soft transition-colors"
                  >
                    <Trash size={14} />
                  </button>
                </li>
              ))}
            </ul>
            <form onSubmit={addExcluded} className="mt-2 flex items-end gap-3">
              <input
                value={notQuoted.name}
                onChange={(event) => setNotQuoted((n) => ({ ...n, name: event.target.value }))}
                placeholder="J.L. Industries"
                aria-label="Vendor CBC does not quote"
                className="flex-1 rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
              <input
                value={notQuoted.reason}
                onChange={(event) => setNotQuoted((n) => ({ ...n, reason: event.target.value }))}
                placeholder="Why - another department's line"
                aria-label="Why CBC does not quote it"
                className="flex-1 rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
              <button
                type="submit"
                disabled={busy}
                className="flex h-[38px] items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
              >
                <Plus size={16} weight="bold" />
                Add
              </button>
            </form>
          </div>

          <form
            onSubmit={addDistributorVendor}
            className="flex items-end gap-3 border-t border-subtle bg-panel-muted px-5 py-4 rounded-b-xl"
          >
            <label className="flex flex-col gap-1.5 flex-1">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Vendor not bought direct
              </span>
              <input
                value={bought.name}
                onChange={(event) => setBought((b) => ({ ...b, name: event.target.value }))}
                placeholder="Pionite"
                aria-label="Vendor bought through a distributor"
                className="w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
            <label className="flex flex-col gap-1.5 flex-1">
              <span className="text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                Bought through
              </span>
              <input
                value={bought.via}
                onChange={(event) => setBought((b) => ({ ...b, via: event.target.value }))}
                placeholder="J2"
                aria-label="Distributors CBC buys it through"
                className="w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border transition-colors shadow-sm"
              />
            </label>
            <button
              type="submit"
              disabled={busy}
              className="flex h-[38px] items-center gap-1.5 rounded-md px-4 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors disabled:opacity-50"
            >
              <Plus size={16} weight="bold" />
              Add
            </button>
          </form>
        </>
      )}
    </section>
  );
}
