"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { usePipelineJob } from "@/hooks/use-pipeline-job";
import { toast } from "sonner";

import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { useUiState } from "@/components/shell/ui-state";
import { useDebounced } from "@/hooks/use-debounced";
import { useDialog } from "@/hooks/use-dialog";
import { formatMoney } from "@/lib/format";
import type { Product, ProductSearchResponse, Project } from "@/lib/types";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import { FetchError } from "@/components/ui/fetch-error";

const STAGES = [
  { key: "intake", label: "Intake" },
  { key: "extraction", label: "Extraction & entry" },
  { key: "quote", label: "Quote" },
  { key: "proposal", label: "Proposal" },
];

const RUNS = [
  { path: "line-items/rerun", label: "Re-run extraction", success: "Claude is re-reading the drawings" },
  { path: "line-items/continue-to-quote", label: "Run pricing", success: "Pricing queued" },
  { path: "quote/continue-to-proposal", label: "Build the proposal", success: "Proposal queued" },
];

/** Ctrl+K. Real actions, not decoration. */
export function CommandPalette({ code }: { code: string | null }) {
  const router = useRouter();
  const { paletteOpen, setPaletteOpen, openNotes, toggleFocus, toggleTheme } = useUiState();
  const [query, setQuery] = useState("");
  const [parts, setParts] = useState<Product[]>([]);

  const close = useCallback(() => setPaletteOpen(false), [setPaletteOpen]);
  const dialogRef = useDialog<HTMLDivElement>(paletteOpen, close);

  const { data: projectData, error: projectsError, mutate: mutateProjects } = useSWR<{ projects: Project[] }>(
    paletteOpen ? "/api/proxy/projects?limit=50" : null,
    proxyFetcher,
  );

  const settled = useDebounced(query.trim());
  // Parts are only searched once the query is specific enough to be useful.
  const searchable = paletteOpen && settled.length >= 2;

  useEffect(() => {
    if (!searchable) return;

    const controller = new AbortController();
    (async () => {
      try {
        const found = await proxyFetcher<ProductSearchResponse>(
          `/api/proxy/catalog/products?q=${encodeURIComponent(settled)}&limit=5`,
          controller.signal,
        );
        setParts(found.products);
      } catch {
        /* aborted, or the catalog is unreachable - the other groups still work */
      }
    })();

    return () => controller.abort();
  }, [settled, searchable]);

  // Derived, so an emptied query never renders the last search's hits.
  const visibleParts = searchable ? parts : [];

  // Opening has to hand over the caret and start from a blank query. Without
  // this the palette opens onto the last search with focus still on the page,
  // so typing goes nowhere and Enter has nothing selected to act on.
  const [wasOpen, setWasOpen] = useState(paletteOpen);
  if (wasOpen !== paletteOpen) {
    setWasOpen(paletteOpen);
    if (paletteOpen) setQuery("");
  }

  useEffect(() => {
    if (!paletteOpen) return;
    const timer = setTimeout(() => {
      document.querySelector<HTMLInputElement>("[cmdk-input]")?.focus();
    }, 0);
    return () => clearTimeout(timer);
  }, [paletteOpen]);

  function run(action: () => void) {
    setPaletteOpen(false);
    setQuery("");
    action();
  }

  const { running: pipelineRunning } = usePipelineJob(code ?? "", null);

  async function enqueue(path: string, success: string) {
    if (!code) {
      toast.error("Open a bid first");
      return;
    }
    if (pipelineRunning) {
      toast.error("A Claude run is already in progress for this bid");
      return;
    }
    try {
      await proxyMutate(`/api/proxy/projects/${code}/${path}`);
      toast.success(success);
      router.refresh();
    } catch (problem) {
      toast.error("That did not go through", { description: errorMessage(problem) });
    }
  }

  if (!paletteOpen) return null;

  // Hand-rolled overlay rather than shadcn's CommandDialog: this build wires the
  // dialog to Base UI and renders DialogTitle outside the dialog root, which
  // reads an undefined store and takes the whole tree down on hydration.
  return (
    <div
      className="fixed inset-0 z-50 flex justify-center px-4 pt-[10vh] sm:pt-[14vh] bg-black/50 backdrop-blur-sm transition-all"
      onClick={(event) => event.target === event.currentTarget && setPaletteOpen(false)}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="animate-in fade-in zoom-in-95 duration-200 h-fit w-full max-w-[620px] overflow-hidden rounded-xl bg-panel border border-subtle shadow-2xl"
      >
        <Command shouldFilter>
      <CommandInput
        placeholder="Ask or run a command…"
        value={query}
        onValueChange={setQuery}
      />
      <CommandList>
        <CommandEmpty>Nothing matches that.</CommandEmpty>

        {query.trim().length >= 1 && (
          <CommandGroup heading="Bids">
            {projectsError ? (
              <div className="px-2 py-1">
                <FetchError
                  title="Could not load bids"
                  error={projectsError}
                  onRetry={() => mutateProjects()}
                  compact
                />
              </div>
            ) : (
              (projectData?.projects ?? []).slice(0, 8).map((project) => (
                <CommandItem
                  key={project.id}
                  value={`${project.code} ${project.name} ${project.brand ?? ""} ${project.gc ?? ""}`}
                  onSelect={() => run(() => router.push(`/bids/${project.code}/${project.stage}`))}
                >
                  <span className="tnum mr-3 font-bold text-brand-primary">
                    {project.code}
                  </span>
                  <span className="flex-1 truncate font-medium">{project.name}</span>
                  <span className="text-[12px] font-medium text-tx-muted ml-2">
                    {project.stage}
                  </span>
                </CommandItem>
              ))
            )}
          </CommandGroup>
        )}

        {code && (
          <CommandGroup heading={`Go to · ${code}`}>
            {STAGES.map((stage) => (
              <CommandItem
                key={stage.key}
                value={`go ${stage.label}`}
                onSelect={() => run(() => router.push(`/bids/${code}/${stage.key}`))}
              >
                {stage.label}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {visibleParts.length > 0 && (
          <CommandGroup heading="Catalog">
            {visibleParts.map((part) => (
              <CommandItem
                key={part.id}
                value={`part ${part.part} ${part.description}`}
                onSelect={() => run(() => router.push(`/catalog?q=${encodeURIComponent(part.part)}`))}
              >
                <span className="mr-3 font-bold">{part.part}</span>
                <span className="flex-1 truncate font-medium text-tx-secondary">
                  {part.description}
                </span>
                <span className="tnum text-[12px] font-bold text-tx-muted ml-2">
                  {part.cost === null ? "manual" : `$${formatMoney(part.cost)}`}
                </span>
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {code && (
          <CommandGroup heading="Run">
            {RUNS.map((entry) => (
              <CommandItem
                key={entry.path}
                value={`run ${entry.label}`}
                disabled={pipelineRunning}
                onSelect={() => run(() => enqueue(entry.path, entry.success))}
              >
                {entry.label}
                {pipelineRunning ? " (run in progress)" : ""}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        <CommandGroup heading="Actions">
          <CommandItem value="log a call note rfi" onSelect={() => run(() => openNotes())}>
            Log a call or note
          </CommandItem>
          <CommandItem value="focus mode" onSelect={() => run(toggleFocus)}>
            Toggle focus mode
          </CommandItem>
          <CommandItem value="theme dark light" onSelect={() => run(toggleTheme)}>
            Toggle theme
          </CommandItem>
          <CommandItem value="bid board" onSelect={() => run(() => router.push("/bids"))}>
            Open the bid board
          </CommandItem>
          <CommandItem value="price books" onSelect={() => run(() => router.push("/price-books"))}>
            Open price books
          </CommandItem>
        </CommandGroup>
      </CommandList>
        </Command>
      </div>
    </div>
  );
}
