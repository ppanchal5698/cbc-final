"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import useSWR from "swr";
import {
  PhoneCall,
  NotePencil,
  Question,
  X,
  PaperPlaneTilt,
  CheckCircle,
} from "@phosphor-icons/react/dist/ssr";
import { toast } from "sonner";

import { useUiState } from "@/components/shell/ui-state";
import { useDialog } from "@/hooks/use-dialog";

import { errorMessage, proxyFetcher, proxyMutate } from "@/lib/proxy-fetcher";
import type { CallEntry, CallsResponse } from "@/lib/types";

const KINDS = [
  { key: "call", label: "Call", Icon: PhoneCall, placeholder: "Who did you speak to, and what was agreed?" },
  { key: "note", label: "Note", Icon: NotePencil, placeholder: "Anything the next person needs to know." },
  { key: "rfi", label: "RFI", Icon: Question, placeholder: "What is unclear, and who has to answer it?" },
] as const;

/** Which stage the note was logged from, so it carries its own context. */
function stageFromPath(pathname: string): string {
  const stage = pathname.split("/").pop() ?? "";
  const labels: Record<string, string> = {
    intake: "Intake",
    extraction: "Extraction & entry",
    quote: "Quote",
    proposal: "Proposal",
  };
  return labels[stage] ?? "Workspace";
}

export function NotesDrawer({ code }: { code: string | null }) {
  const { notesOpen, closeNotes, notesRef, bumpNotes } = useUiState();
  const pathname = usePathname();
  const [kind, setKind] = useState<(typeof KINDS)[number]["key"]>("call");
  const [text, setText] = useState("");
  const [org, setOrg] = useState("");
  const [busy, setBusy] = useState(false);
  const dialogRef = useDialog<HTMLDivElement>(notesOpen, closeNotes);

  const { data, error, mutate } = useSWR<CallsResponse>(
    notesOpen && code ? `/api/proxy/projects/${code}/calls` : null,
    proxyFetcher,
  );

  if (!notesOpen) return null;

  const active = KINDS.find((entry) => entry.key === kind)!;

  async function submit() {
    if (!code) {
      toast.error("Open a bid first", { description: "Notes are saved against an estimate." });
      return;
    }
    if (!text.trim()) return;

    setBusy(true);
    try {
      await proxyMutate(`/api/proxy/projects/${code}/calls`, {
        body: {
          kind,
          text: text.trim(),
          org: org.trim() || null,
          ref: notesRef ?? stageFromPath(pathname),
        },
      });
      toast.success(`${active.label} logged`, { description: "It travels with the estimate." });
      setText("");
      setOrg("");
      mutate();
      bumpNotes();
    } catch (problem) {
      toast.error("Could not log that", { description: errorMessage(problem) });
    } finally {
      setBusy(false);
    }
  }

  async function resolve(entry: CallEntry) {
    try {
      // This used to report success without ever checking the response.
      await proxyMutate(`/api/proxy/projects/${code}/calls/${entry.id}/resolve`);
      toast.success("RFI closed");
      mutate();
      bumpNotes();
    } catch (problem) {
      toast.error("Could not close that RFI", { description: errorMessage(problem) });
    }
  }

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label="Log a call or note"
    >
      <div className="flex-1 bg-black/50 backdrop-blur-sm transition-all" onClick={closeNotes} />

      <aside className="flex w-full max-w-[460px] flex-col bg-panel border-l border-subtle shadow-2xl animate-in slide-in-from-right-full duration-300">
        <div className="flex items-center gap-4 border-b border-subtle px-6 py-5 bg-panel-muted">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-primary/10 text-brand-primary border border-brand-primary/20 shadow-sm">
            <PhoneCall size={20} weight="duotone" />
          </span>
          <span className="flex flex-1 flex-col leading-tight gap-1">
            <span className="text-[16px] font-bold tracking-tight text-tx-primary">Log a call or note</span>
            <span className="text-[12.5px] font-medium text-tx-muted">
              {code
                ? `Saved against ${code} · travels with the estimate`
                : "Open a bid to log against it"}
            </span>
          </span>
          <button onClick={closeNotes} aria-label="Close" className="text-tx-muted hover:text-tx-primary hover:bg-background p-1.5 rounded-md transition-colors focus:ring-2 focus:ring-brand-border outline-none">
            <X size={18} weight="bold" />
          </button>
        </div>

        <div className="border-b border-subtle px-6 py-5 bg-panel">
          <div className="flex gap-1.5">
            {KINDS.map((entry) => {
              const on = entry.key === kind;
              return (
                <button
                  key={entry.key}
                  onClick={() => setKind(entry.key)}
                  className={`flex flex-1 items-center justify-center gap-2 rounded-lg py-2 text-[13px] font-bold transition-all shadow-sm ${
                    on 
                      ? "bg-brand-primary/10 text-brand-primary border border-brand-primary/20" 
                      : "bg-background text-tx-secondary border border-subtle hover:bg-panel-muted hover:text-tx-primary"
                  }`}
                >
                  <entry.Icon size={16} weight={on ? "fill" : "duotone"} />
                  {entry.label}
                </button>
              );
            })}
          </div>

          <input
            value={org}
            onChange={(event) => setOrg(event.target.value)}
            placeholder="Who it was with — GC, architect, vendor"
            aria-label="Who it was with"
            className="mt-4 w-full rounded-lg px-3 py-2.5 text-[13.5px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-2 focus:ring-brand-border transition-colors shadow-sm"
          />

          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder={active.placeholder}
            aria-label={`${active.label} text`}
            rows={4}
            className="mt-3 w-full resize-none rounded-lg px-3 py-2.5 text-[13.5px] font-medium outline-none border border-subtle bg-background text-tx-primary placeholder:text-tx-muted focus:ring-2 focus:ring-brand-border transition-colors shadow-sm"
          />

          <div className="mt-4 flex items-center gap-3">
            <span className="flex-1 text-[12px] font-medium text-tx-muted">
              Logged against {notesRef ?? stageFromPath(pathname)}
            </span>
            <button
              onClick={closeNotes}
              className="rounded-md px-4 py-2 text-[13px] font-bold border border-subtle bg-background text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
            >
              Cancel
            </button>
            <button
              onClick={submit}
              disabled={busy || !text.trim()}
              className="flex items-center gap-2 rounded-md px-4 py-2 text-[13px] font-bold disabled:opacity-50 transition-all bg-brand-primary text-white hover:bg-brand-primary/90 shadow-sm"
            >
              <PaperPlaneTilt size={16} weight="fill" />
              Log it
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-6 py-4 bg-background">
          {error ? (
            <p className="py-10 text-center text-[13px] font-medium text-status-error bg-status-error-soft rounded-lg border border-status-error/30 mt-4">
              Could not load what has been logged: {errorMessage(error)}
            </p>
          ) : (data?.calls ?? []).length === 0 ? (
            <p className="py-12 text-center text-[13.5px] font-medium text-tx-muted">
              Nothing logged on this bid yet.
            </p>
          ) : (
            (data?.calls ?? []).map((entry) => {
              const meta = KINDS.find((k) => k.key === entry.kind) ?? KINDS[0];
              const open = entry.kind === "rfi" && !entry.resolvedAt;
              return (
                <div
                  key={entry.id}
                  className="border-b border-subtle py-4 last:border-b-0 group"
                >
                  <div className="flex items-start gap-3">
                    <meta.Icon
                      size={18}
                      weight="duotone"
                      className={`mt-0.5 ${open ? "text-status-warning" : "text-tx-muted"}`}
                    />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline gap-2">
                        <span className="text-[14px] font-bold text-tx-primary">{entry.who}</span>
                        {open && (
                          <span className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-widest bg-status-warning-soft text-status-warning">
                            open RFI
                          </span>
                        )}
                      </div>
                      <div className="text-[12px] font-medium text-tx-muted mt-0.5">
                        {entry.org ? `${entry.org} · ` : ""}
                        {new Date(entry.createdAt).toLocaleString()}
                        {entry.ref ? ` · ${entry.ref}` : ""}
                      </div>
                      <p className="mt-2 text-[13.5px] font-medium text-tx-secondary leading-relaxed">
                        {entry.text}
                      </p>
                    </div>
                    {open && (
                      <button
                        onClick={() => resolve(entry)}
                        title="Mark this RFI answered"
                        aria-label={`Mark the RFI from ${entry.who} answered`}
                        className="text-tx-muted hover:text-status-success transition-colors p-1.5 rounded-md hover:bg-status-success-soft"
                      >
                        <CheckCircle size={20} weight="fill" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </aside>
    </div>
  );
}
