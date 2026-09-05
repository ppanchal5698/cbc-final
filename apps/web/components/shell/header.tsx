"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { signOut } from "next-auth/react";
import { MagnifyingGlass, Sun, Moon, PhoneCall } from "@phosphor-icons/react/dist/ssr";

import { ReviewQueuePopover } from "@/components/shell/review-queue-popover";
import { useUiState } from "@/components/shell/ui-state";
import { proxyFetcher } from "@/lib/proxy-fetcher";
import type { CallsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

export interface Crumb {
  label: string;
  href?: string;
}

function roleLabel(role: string): string {
  if (role === "admin") return "Admin";
  return "Estimator";
}

export function Header({
  crumbs,
  user,
  runPill,
  reviewCount,
  code,
}: {
  crumbs: Crumb[];
  user: { name: string; initials: string; role: string };
  runPill?: { label: string; tone: "running" | "done" | "failed" } | null;
  reviewCount?: number;
  code?: string | null;
}) {
  const { openNotes, setPaletteOpen, setTerminalOpen, focusMode, notesVersion, theme, toggleTheme } =
    useUiState();
  const [noteCount, setNoteCount] = useState<number | null>(null);

  useEffect(() => {
    if (!code) return;
    const controller = new AbortController();
    proxyFetcher<CallsResponse>(`/api/proxy/projects/${code}/calls`, controller.signal)
      .then((data) => setNoteCount(data.count))
      .catch(() => setNoteCount(null));
    return () => controller.abort();
  }, [code, notesVersion]);

  const toneColourClass =
    runPill?.tone === "failed"
      ? "bg-status-error"
      : runPill?.tone === "running"
        ? "bg-status-warning"
        : "bg-status-success";

  return (
    <header className="flex h-[54px] shrink-0 items-center gap-4 border-b border-subtle bg-background px-5">
      <div className="flex items-center gap-1.5 text-[13px] font-medium">
        {crumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex items-center gap-1.5">
            {index > 0 && <span className="text-tx-muted">/</span>}
            {crumb.href ? (
              <Link href={crumb.href} className="text-tx-secondary no-underline hover:text-tx-primary transition-colors">
                {crumb.label}
              </Link>
            ) : (
              <span className="text-tx-primary">{crumb.label}</span>
            )}
          </span>
        ))}
      </div>

      <div className="flex-1" />

      <button
        onClick={() => setPaletteOpen(true)}
        aria-keyshortcuts="Control+K"
        className="hidden h-[34px] w-[200px] items-center gap-2 rounded-lg border border-subtle bg-panel px-3 transition-colors hover:border-brand-border hover:bg-panel-muted md:flex xl:w-[330px] shadow-sm"
      >
        <MagnifyingGlass size={15} weight="duotone" className="text-tx-muted" />
        <span className="flex-1 truncate text-left text-[13px] text-tx-muted">
          Ask or run a command…
        </span>
        <span className="hidden rounded bg-panel-muted px-1.5 py-0.5 text-[10.5px] text-tx-muted border border-subtle xl:inline font-medium">
          Ctrl K
        </span>
      </button>

      {runPill && !focusMode && (
        <button
          onClick={() => setTerminalOpen(true)}
          aria-label="View run status"
          className="animate-fade-in flex items-center gap-2 rounded-full border border-subtle bg-panel px-3 py-1.5 text-[12px] transition-colors hover:bg-panel-muted shadow-sm"
        >
          <span className={cn("h-1.5 w-1.5 rounded-full animate-pulse", toneColourClass)} />
          <span className="text-tx-secondary font-medium">{runPill.label}</span>
        </button>
      )}

      <button
        onClick={() => openNotes()}
        className="flex items-center gap-1.5 rounded-md border border-subtle bg-background px-2.5 py-1.5 text-[12px] text-tx-secondary transition-colors hover:bg-panel-muted shadow-sm font-medium"
      >
        <PhoneCall size={14} weight="duotone" className="text-tx-muted" />
        Calls &amp; notes
        {noteCount !== null && noteCount > 0 && (
          <span className="tnum rounded-full bg-brand-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-brand-primary">
            {noteCount}
          </span>
        )}
      </button>

      <button
        onClick={toggleTheme}
        aria-label="Toggle theme"
        className="grid h-8 w-8 place-items-center rounded-md text-tx-secondary transition-colors hover:bg-panel-muted hover:text-tx-primary"
      >
        {theme === "dark" ? <Sun size={16} weight="duotone" /> : <Moon size={16} weight="duotone" />}
      </button>

      <ReviewQueuePopover reviewCount={reviewCount} code={code} />

      <div className="flex items-center gap-2.5 border-l border-subtle pl-4 ml-1">
        <span className="grid h-8 w-8 place-items-center rounded-full bg-brand-soft text-[11.5px] font-semibold text-brand-primary shadow-sm">
          {user.initials}
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-[12.5px] font-semibold text-tx-primary">{user.name}</span>
          <span className="text-[11px] text-tx-muted font-medium">
            {roleLabel(user.role)}
          </span>
        </span>
        <button
          onClick={() => signOut({ callbackUrl: "/signin" })}
          className="text-[12px] text-tx-muted hover:text-tx-primary transition-colors ml-2 font-medium"
        >
          Sign out
        </button>
      </div>
    </header>
  );
}
