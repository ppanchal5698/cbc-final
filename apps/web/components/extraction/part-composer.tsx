"use client";

import { useEffect, useState } from "react";
import { PlusCircle } from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { useDebounced } from "@/hooks/use-debounced";
import { formatMoney } from "@/lib/format";
import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { LineItem, Product, ProductSearchResponse } from "@/lib/types";

/**
 * "Add anything the drawings do not carry."
 *
 * Searches the live catalog by part number, description, manufacturer or
 * division. A free-typed description is allowed too - not everything an
 * estimator needs to add exists in the catalog yet.
 */
export function PartComposer({ code, onAdded }: { code: string; onAdded: () => void }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Product[]>([]);
  const [busy, setBusy] = useState(false);
  const [focused, setFocused] = useState(false);

  const settled = useDebounced(query.trim());
  const tooShort = settled.length < 2;

  useEffect(() => {
    if (tooShort) return;

    // Aborting the superseded request is what stops a slow early response from
    // landing on top of a fast later one.
    const controller = new AbortController();
    (async () => {
      try {
        const found = await proxyFetcher<ProductSearchResponse>(
          `/api/proxy/catalog/products?q=${encodeURIComponent(settled)}&limit=6`,
          controller.signal,
        );
        setHits(found.products);
      } catch {
        /* aborted, or the search failed - the composer still accepts free text */
      }
    })();

    return () => controller.abort();
  }, [settled, tooShort]);

  // Derived rather than cleared in an effect, so a stale list is never rendered
  // for one frame after the query is emptied.
  const visible = tooShort ? [] : hits;

  async function add(product?: Product) {
    const description = product?.description ?? query.trim();
    if (!description) return;

    setBusy(true);
    try {
      await proxyMutate<LineItem>(`/api/proxy/projects/${code}/line-items`, {
        body: {
          description,
          part: product?.part,
          division: product?.division,
          qty: 1,
        },
      });
      toast.success(product ? `${product.part} added` : "Line added", {
        description: "Marked as added by hand, and already confirmed.",
      });
      setQuery("");
      setHits([]);
      onAdded();
    } catch (problem) {
      toast.error("Could not add that line", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative">
      <div className="flex items-center gap-3 rounded-xl px-5 py-3.5 bg-panel border border-subtle shadow-sm hover:shadow-md transition-shadow">
        <PlusCircle size={20} weight="fill" className="text-status-error shrink-0" />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 160)}
          onKeyDown={(event) => {
            if (event.key === "Enter") add();
          }}
          placeholder="Add anything the drawings do not carry — search a part number or type a description"
          aria-label="Add a line by hand"
          className="min-w-0 flex-1 bg-transparent text-[14px] font-medium text-tx-primary outline-none placeholder:text-tx-muted"
        />
        <span className="hidden text-[11px] font-bold uppercase tracking-widest text-tx-muted sm:inline px-2">
          ↵ add
        </span>
        <button
          onClick={() => add()}
          disabled={busy || query.trim().length === 0}
          className="shrink-0 rounded-lg px-4 py-2 text-[13px] font-bold disabled:opacity-50 transition-colors bg-status-error text-white hover:bg-status-error/90 shadow-sm"
        >
          Add line
        </button>
      </div>

      {focused && visible.length > 0 && (
        <div className="anim-fadein absolute bottom-full left-0 right-0 z-20 mb-3 overflow-hidden rounded-xl bg-panel border border-subtle shadow-2xl">
          {visible.map((product) => (
            <button
              key={product.id}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => add(product)}
              className="grid w-full items-center gap-4 border-b border-subtle px-5 py-3 text-left last:border-b-0 hover:bg-background/50 transition-colors"
              style={{
                gridTemplateColumns: "minmax(120px,170px) 1fr 110px 90px",
              }}
            >
              <span className="truncate text-[13px] font-bold text-brand-primary tracking-tight">
                {product.part}
              </span>
              <span className="truncate text-[13px] font-medium text-tx-primary">{product.description}</span>
              <span className="truncate text-[12px] font-medium text-tx-muted">
                {product.manufacturer ?? "—"}
              </span>
              <span className="tnum text-right text-[12.5px] font-bold text-tx-secondary">
                {product.cost === null ? "manual" : `$${formatMoney(product.cost)}`}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
