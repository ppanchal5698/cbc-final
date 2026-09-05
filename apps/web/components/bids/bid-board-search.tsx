"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { MagnifyingGlass, X } from "@phosphor-icons/react/dist/ssr";

import { useDebounced } from "@/hooks/use-debounced";

/** Debounced bid board search wired to the `?q=` URL param. */
export function BidBoardSearch({
  stage,
  initialQuery = "",
}: {
  stage?: string;
  initialQuery?: string;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(initialQuery);
  const settled = useDebounced(query.trim());

  useEffect(() => {
    if (settled === initialQuery.trim()) return;

    const params = new URLSearchParams();
    if (stage && stage !== "all") params.set("stage", stage);
    if (settled) params.set("q", settled);

    const qs = params.toString();
    router.replace(qs ? `/bids?${qs}` : "/bids");
  }, [settled, initialQuery, router, stage]);

  return (
    <div className="relative flex h-9 w-full max-w-sm items-center gap-2 rounded-lg px-3 bg-panel border border-subtle shadow-sm transition-colors focus-within:border-brand-border focus-within:ring-1 focus-within:ring-brand-border/30">
      <MagnifyingGlass size={15} weight="duotone" className="text-tx-muted" />
      <input
        type="text"
        role="searchbox"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search bids by code, name, brand…"
        aria-label="Search bids"
        className="min-w-0 flex-1 bg-transparent text-[13px] text-tx-primary outline-none placeholder:text-tx-muted"
      />
      {query && (
        <button
          type="button"
          onClick={() => setQuery("")}
          aria-label="Clear search"
          className="rounded p-0.5 text-tx-muted hover:text-tx-primary transition-colors hover:bg-panel-muted"
        >
          <X size={14} weight="bold" />
        </button>
      )}
    </div>
  );
}
