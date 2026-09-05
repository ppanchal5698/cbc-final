"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  Package,
  Plus,
  Trash,
  FloppyDisk,
  MagnifyingGlass,
  Lock,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { AddToBid } from "@/components/catalog/add-to-bid";
import { useDebounced } from "@/hooks/use-debounced";
import { formatMoney } from "@/lib/format";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { Product, ProductSearchResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

const EDIT_FIELDS = [
  { key: "description", label: "Description", type: "text" },
  { key: "manufacturer", label: "Manufacturer", type: "text" },
  { key: "division", label: "Division", type: "text" },
  { key: "cost", label: "Our cost", type: "number" },
  { key: "listPrice", label: "List", type: "number" },
  { key: "multiplier", label: "Multiplier", type: "number" },
  { key: "availability", label: "Availability", type: "text" },
] as const;

const COLUMNS = "190px minmax(220px,1fr) 130px 90px 100px 110px";

/**
 * A price means nothing without its basis. Every indexed price used to be shown as
 * "list $X"; on a vendor bought at a flat net that is the cost already, and reading
 * it as list invites multiplying it down a second time. Say which one it is, and
 * say so plainly when the sheet does not tell us.
 */
function priceLabel(product: Product): string {
  if (product.priceBasis === "net" && product.netPrice !== null && product.netPrice !== undefined) {
    return `net $${formatMoney(product.netPrice)}`;
  }
  if (product.listPrice !== null) return `list $${formatMoney(product.listPrice)}`;
  if (product.priceBasis === "unknown" && product.price !== null && product.price !== undefined) {
    return `$${formatMoney(product.price)} ?`;
  }
  return "—";
}

function draftFor(product: Product): Record<string, string> {
  return {
    description: product.description ?? "",
    manufacturer: product.manufacturer ?? "",
    division: product.division ?? "",
    cost: product.cost === null ? "" : String(product.cost),
    listPrice: product.listPrice === null ? "" : String(product.listPrice),
    multiplier: product.multiplier === null ? "" : String(product.multiplier),
    availability: product.availability ?? "",
  };
}

export function CatalogClient({ initialQuery = "" }: { initialQuery?: string }) {
  const [query, setQuery] = useState(initialQuery);
  const [division, setDivision] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [edits, setEdits] = useState<{ id: string; values: Record<string, string> } | null>(null);

  // One request once typing settles, not one per keystroke.
  const settledQuery = useDebounced(query.trim());

  const params = new URLSearchParams();
  if (settledQuery) params.set("q", settledQuery);
  if (division) params.set("division", division);

  const { data, error, isLoading, mutate } = useSWR<ProductSearchResponse>(
    `/api/proxy/catalog/products?${params.toString()}`,
    proxyFetcher,
    { keepPreviousData: true },
  );

  const products = data?.products ?? [];
  // Pages of the vendor price books. Deliberately not merged into the product
  // list: a page is somewhere to look, not a priced line, and showing the two as
  // one list is what let page furniture pass for a product.
  const pages = data?.pages ?? [];
  const selected = products.find((product) => product.id === selectedId) ?? null;
  // Indexed rows are rebuilt from the vendor PDF on every reindex and carry an
  // `idx:` id the API cannot resolve, so they are shown read-only rather than
  // offering a Save that returns 400.
  const editable = selected?.editable !== false;

  // The panel follows the selected row without an effect: a different part is a
  // different draft, so the identity of the row is what resets it.
  const draft = selected
    ? edits?.id === selected.id
      ? edits.values
      : draftFor(selected)
    : {};

  function setField(key: string, value: string) {
    if (!selected) return;
    setEdits({ id: selected.id, values: { ...draft, [key]: value } });
  }

  async function save() {
    if (!selected || !editable) return;
    const body: Record<string, unknown> = {};
    for (const field of EDIT_FIELDS) {
      const value = draft[field.key]?.trim() ?? "";
      body[field.key] =
        field.type === "number" ? (value === "" ? null : Number(value)) : value || null;
    }

    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/catalog/products/${selected.id}`, {
        method: "PATCH",
        body,
      });
      toast.success(`${selected.part} saved`);
      setEdits(null);
      mutate();
    } catch (problem) {
      toast.error("Could not save that part", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selected || !editable) return;
    if (
      !window.confirm(
        `Remove ${selected.part} from the catalog? Quote lines already priced from it keep their price.`,
      )
    ) {
      return;
    }

    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/catalog/products/${selected.id}`, { method: "DELETE" });
      toast.success(`${selected.part} removed`);
      setSelectedId(null);
      setEdits(null);
      mutate();
    } catch (problem) {
      toast.error("Could not remove that part", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function create(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const part = String(form.get("part") ?? "").trim();

    setBusy(true);
    try {
      await proxyMutate("/api/proxy/catalog/products", {
        body: {
          part,
          description: String(form.get("description") ?? "").trim(),
          manufacturer: String(form.get("manufacturer") ?? "").trim() || null,
          division: String(form.get("division") ?? "").trim() || null,
          cost: form.get("cost") ? Number(form.get("cost")) : null,
        },
      });
      toast.success(`${part} added to the catalog`);
      setCreating(false);
      mutate();
    } catch (problem) {
      toast.error("Could not add that part", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-0 flex-1 flex-col gap-6 overflow-auto p-8 bg-background lg:flex-row lg:overflow-hidden">
      <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-[26px] font-bold tracking-tight text-tx-primary">Product catalog</h1>
            <p className="mt-1.5 text-[14px] font-medium text-tx-secondary">
              {data?.total ?? 0} of your own parts
              {pages.length > 0 ? ` · ${pages.length} price-book page${pages.length === 1 ? "" : "s"} match` : ""}
            </p>
          </div>
          <button
            onClick={() => setCreating((c) => !c)}
            className="flex items-center gap-1.5 rounded-md px-3.5 py-2 text-[13px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
          >
            <Plus size={14} weight="bold" />
            Add part
          </button>
        </div>

        {creating && (
          <form
            onSubmit={create}
            className="animate-fade-in grid gap-3 rounded-xl p-4 bg-panel border border-subtle shadow-sm sm:grid-cols-2 xl:grid-cols-[170px_1fr_130px_110px_100px_90px]"
          >
            {[
              { name: "part", placeholder: "Part number", required: true },
              { name: "description", placeholder: "Description", required: true },
              { name: "manufacturer", placeholder: "Manufacturer" },
              { name: "division", placeholder: "08 71 00" },
              { name: "cost", placeholder: "Cost", type: "number" },
            ].map((field) => (
              <input
                key={field.name}
                name={field.name}
                type={field.type ?? "text"}
                step={field.type === "number" ? "0.01" : undefined}
                required={field.required}
                placeholder={field.placeholder}
                aria-label={field.placeholder}
                className="rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm"
              />
            ))}
            <button
              type="submit"
              disabled={busy}
              className="rounded-md py-2 text-[13px] font-semibold disabled:opacity-60 bg-status-success text-white shadow-sm hover:bg-status-success/90 transition-colors"
            >
              Save
            </button>
          </form>
        )}

        <div className="flex items-center gap-2 rounded-xl px-4 py-2.5 bg-panel border border-subtle shadow-sm transition-colors focus-within:border-brand-border focus-within:ring-1 focus-within:ring-brand-border/30">
          <MagnifyingGlass size={16} weight="duotone" className="text-tx-muted" />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Part number, description, manufacturer"
            aria-label="Search the catalog"
            className="min-w-0 flex-1 bg-transparent text-[13px] text-tx-primary outline-none placeholder:text-tx-muted"
          />
          <span className="tnum shrink-0 text-[12px] font-medium text-tx-muted">
            {products.length} of {data?.total ?? 0}
          </span>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => setDivision("")}
            className={cn(
              "rounded-md px-3.5 py-1.5 text-[12.5px] font-medium transition-colors shadow-sm",
              division === "" 
                ? "bg-brand-soft border border-brand-border text-brand-primary" 
                : "bg-panel border border-subtle text-tx-secondary hover:text-tx-primary hover:bg-panel-muted"
            )}
          >
            All divisions {data?.total ?? 0}
          </button>
          {(data?.divisions ?? []).map((entry) => (
            <button
              key={entry.division}
              onClick={() => setDivision(entry.division)}
              className={cn(
                "rounded-md px-3.5 py-1.5 text-[12.5px] font-medium transition-colors shadow-sm",
                division === entry.division 
                  ? "bg-brand-soft border border-brand-border text-brand-primary" 
                  : "bg-panel border border-subtle text-tx-secondary hover:text-tx-primary hover:bg-panel-muted"
              )}
            >
              {entry.division} {entry.count}
            </button>
          ))}
        </div>

        <div className="min-h-[240px] flex-1 overflow-auto rounded-xl bg-panel border border-subtle shadow-sm lg:min-h-0">
          <div style={{ minWidth: 840 }}>
            <div
              className="sticky top-0 z-10 grid gap-3 border-b border-subtle px-4 py-2.5 text-[10.5px] font-bold uppercase tracking-widest text-tx-muted bg-panel/80 backdrop-blur-md"
              style={{ gridTemplateColumns: COLUMNS }}
            >
              <span>Part</span>
              <span>Description</span>
              <span>Manufacturer</span>
              <span className="text-right">Cost</span>
              <span>Division</span>
              <span>Availability</span>
            </div>

            {error ? (
              <div className="grid place-items-center gap-2 px-6 py-16 text-center">
                <span className="text-[13.5px] font-semibold text-status-error">
                  Could not load the catalog
                </span>
                <span className="max-w-[420px] text-[12.5px] text-tx-secondary">
                  {errorMessage(error)}
                </span>
                <button
                  onClick={() => mutate()}
                  className="mt-1 rounded-md px-3 py-1.5 text-[12.5px] font-medium border border-subtle text-tx-secondary hover:bg-panel-muted transition-colors"
                >
                  Try again
                </button>
              </div>
            ) : isLoading && products.length === 0 ? (
              <div className="grid place-items-center px-6 py-16 text-center">
                <span className="text-[12.5px] font-medium text-tx-muted">
                  Searching the catalog…
                </span>
              </div>
            ) : products.length === 0 ? (
              <div className="grid place-items-center gap-1.5 px-6 py-16 text-center">
                <span className="text-[14px] font-semibold text-tx-primary">
                  {data?.indexAvailable === false
                    ? "The catalog index has not been built"
                    : "No parts match"}
                </span>
                <span className="max-w-[460px] text-[12.5px] text-tx-secondary">
                  {/* The API says exactly why it is empty. Showing "no matches"
                      for an unbuilt index sent people looking for the wrong problem. */}
                  {data?.note ??
                    (pages.length > 0
                      ? "None of your own parts match, but the price books have pages that do — see below."
                      : settledQuery || division
                        ? "Nothing here matches that search. Clear the filters, or add the part by hand."
                        : "Search for a part number or description to find the page it is on.")}
                </span>
              </div>
            ) : (
              products.map((product) => (
                <button
                  key={product.id}
                  onClick={() => setSelectedId(product.id)}
                  aria-current={selectedId === product.id}
                  className={cn(
                    "grid w-full items-center gap-3 border-b border-subtle px-4 py-3 text-left last:border-b-0 transition-colors hover:bg-panel-muted",
                    selectedId === product.id && "bg-brand-soft/30"
                  )}
                  style={{ gridTemplateColumns: COLUMNS }}
                >
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[13px] font-semibold text-tx-primary">{product.part}</span>
                    {product.editable === false && (
                      <Lock size={12} weight="bold" className="text-tx-muted shrink-0" />
                    )}
                  </span>
                  <span className="truncate text-[12.5px] text-tx-secondary font-medium">
                    {product.description}
                  </span>
                  <span className="truncate text-[12.5px] text-tx-secondary font-medium">
                    {product.manufacturer ?? "—"}
                  </span>
                  <span className="tnum text-right text-[13px] font-medium text-tx-primary">
                    {product.cost === null
                      ? priceLabel(product)
                      : `$${formatMoney(product.cost)}`}
                  </span>
                  <span className="tnum truncate text-[12.5px] font-medium text-tx-muted">
                    {product.division ?? "—"}
                  </span>
                  <span
                    className={cn(
                      "truncate text-[12.5px] font-medium",
                      product.availability?.toLowerCase().includes("long") ||
                        product.availability?.toLowerCase().includes("custom")
                        ? "text-status-error"
                        : "text-tx-secondary"
                    )}
                  >
                    {product.availability ?? "—"}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      </section>

      {pages.length > 0 && (
        <section className="flex min-h-0 min-w-0 flex-col gap-3 lg:max-w-[420px]">
          <div>
            <h2 className="text-[15px] font-semibold text-tx-primary">In the price books</h2>
            <p className="mt-0.5 text-[12.5px] font-medium text-tx-secondary">
              {data?.pagesNote ?? "Pages worth opening. The price is on the page."}
            </p>
          </div>
          <ul className="flex min-h-0 flex-col gap-2 overflow-auto pr-1">
            {pages.map((page) => (
              <li
                key={`${page.catalog_id}-${page.pdf_page}`}
                className="flex flex-col gap-1.5 rounded-lg p-3.5 bg-panel border border-subtle shadow-sm transition-colors hover:border-brand-border/40"
              >
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] font-semibold text-tx-primary">{page.title}</span>
                  <span className="tnum shrink-0 text-[11.5px] font-medium text-tx-muted">
                    {page.locator}
                  </span>
                </div>
                <span className="text-[12.5px] font-medium text-tx-secondary">
                  {page.description}
                </span>
                <div className="flex flex-wrap items-center gap-2 text-[11.5px] font-medium mt-1">
                  <span className="text-tx-muted">{page.vendor}</span>
                  {page.has_prices && (
                    <span className="rounded bg-panel-muted border border-subtle px-1.5 py-0.5 text-tx-secondary">
                      {page.price_basis === "net" ? "net prices" : "list prices"}
                    </span>
                  )}
                  {page.code_prefixes.slice(0, 3).map((code) => (
                    <span key={code} className="tnum text-tx-muted">
                      {code}
                    </span>
                  ))}
                </div>
                {/* Why it matched, so a page that is not what you wanted is
                    legible rather than mysterious. */}
                <span className="text-[11px] font-medium text-tx-muted mt-0.5">
                  {page.why.join(" · ")}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <aside className="flex shrink-0 flex-col overflow-auto rounded-xl lg:w-[360px] bg-panel border border-subtle shadow-sm">
        {!selected ? (
          <div className="grid flex-1 place-items-center gap-2 px-6 py-10 text-center">
            <Package size={32} weight="duotone" className="text-tx-muted mb-2" />
            <span className="text-[13px] font-medium text-tx-secondary">
              Pick a part to see and edit its pricing.
            </span>
          </div>
        ) : (
          <div className="p-5">
            <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
              {selected.manufacturer ?? "—"} · {selected.division ?? "—"}
            </span>
            <h2 className="mt-1 text-[18px] font-semibold text-tx-primary leading-tight">{selected.part}</h2>
            <p className="mt-1.5 text-[13px] font-medium text-tx-secondary">
              {selected.description}
            </p>

            {selected.seedSource === "prototype sample" && (
              <p className="mt-4 rounded-md px-3 py-2.5 text-[12px] font-medium bg-status-warning-soft border border-status-warning/30 text-status-warning">
                Sample figures from the design, not confirmed CBC pricing. Ingest the real price
                book, or correct them here.
              </p>
            )}

            {!editable ? (
              <>
                <p className="mt-4 flex items-start gap-2.5 rounded-md px-3 py-2.5 text-[12px] font-medium bg-panel-muted border border-subtle text-tx-secondary">
                  <Lock size={14} weight="duotone" className="mt-px shrink-0 text-tx-muted" />
                  <span>
                    Read from the vendor price book, so it is not edited here — the next reindex
                    rewrites it from the PDF. Correct the sheet, or add your own part.
                  </span>
                </p>

                <div className="mt-5 flex flex-col gap-2.5">
                  {[
                    [
                      selected.priceBasis === "net"
                        ? "Net price"
                        : selected.priceBasis === "unknown"
                          ? "Price (basis unrecorded)"
                          : "List price",
                      priceLabel(selected).replace(/^(list|net) /, ""),
                    ],
                    ["Basis", selected.priceBasisNote ?? "—"],
                    ["Unit", selected.unit ?? "—"],
                    ["Price book", selected.priceBook ?? "—"],
                    ["Page", selected.sourcePage ? String(selected.sourcePage) : "—"],
                    ["Effective", selected.effective ?? "not recorded"],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex items-baseline justify-between gap-3 border-b border-subtle pb-2 last:border-b-0"
                    >
                      <span className="shrink-0 text-[11.5px] font-medium text-tx-muted">
                        {label}
                      </span>
                      <span className="truncate text-right text-[12.5px] font-medium text-tx-primary">{value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="mt-5 flex flex-col gap-3">
                {EDIT_FIELDS.map((field) => (
                  <label key={field.key} className="block">
                    <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted">
                      {field.label}
                    </span>
                    <input
                      type={field.type}
                      step={field.type === "number" ? "0.001" : undefined}
                      value={draft[field.key] ?? ""}
                      onChange={(event) => setField(field.key, event.target.value)}
                      className="mt-1.5 w-full rounded-md px-3 py-2 text-[13px] outline-none border border-subtle bg-background text-tx-primary focus:ring-1 focus:ring-brand-border focus:border-brand-border transition-colors shadow-sm"
                    />
                  </label>
                ))}
              </div>
            )}

            <div className="mt-6 flex items-center justify-between rounded-md px-3.5 py-3 bg-panel-muted border border-subtle shadow-sm">
              <span className="text-[12px] font-semibold text-tx-muted">
                Sell at
              </span>
              <span className="tnum text-[16px] font-bold text-brand-primary">
                {selected.sellAt == null ? "—" : `$${formatMoney(selected.sellAt)}`}
              </span>
            </div>
            <p className="mt-2 text-[11.5px] font-medium text-tx-muted leading-relaxed">
              Sell follows the division&apos;s margin divisor. Overriding it on a quote line is
              logged against your name.
            </p>

            {(selected.xref?.length ?? 0) > 0 && (
              <div className="mt-5">
                <span className="block text-[11px] font-bold uppercase tracking-widest text-tx-muted mb-2">
                  Cross-reference
                </span>
                {selected.xref?.map((entry) => (
                  <div
                    key={`${entry.manufacturer}-${entry.part}`}
                    className="flex justify-between border-b border-subtle py-2 last:border-b-0"
                  >
                    <span className="text-[12.5px] font-medium text-tx-secondary">
                      {entry.manufacturer}
                    </span>
                    <span className="text-[12.5px] font-medium text-tx-primary">{entry.part}</span>
                  </div>
                ))}
              </div>
            )}

            <div className="mt-5">
              <AddToBid product={selected} />
            </div>

            {editable && (
              <div className="mt-6 flex gap-3">
                <button
                  onClick={save}
                  disabled={busy}
                  className="flex flex-1 items-center justify-center gap-1.5 rounded-md py-2.5 text-[13px] font-semibold disabled:opacity-60 bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
                >
                  <FloppyDisk size={16} weight="duotone" />
                  Save
                </button>
                <button
                  onClick={remove}
                  disabled={busy}
                  aria-label={`Remove ${selected.part}`}
                  className="flex items-center justify-center gap-1.5 rounded-md px-4 py-2.5 text-[13px] disabled:opacity-60 border border-status-error/30 text-status-error hover:bg-status-error-soft transition-colors shadow-sm"
                >
                  <Trash size={16} weight="duotone" />
                </button>
              </div>
            )}
          </div>
        )}
      </aside>
    </main>
  );
}
