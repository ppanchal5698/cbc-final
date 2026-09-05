"use client";

import Link from "next/link";

import { isAdminRole, translateJobError, type JobErrorAction } from "@/lib/job-error";
import type { Job } from "@/lib/types";

export function JobFailedBanner({
  job,
  role,
  stage,
  onAction,
}: {
  job: Job;
  role: string;
  stage: "extraction" | "quote" | "proposal" | "intake";
  onAction?: (action: JobErrorAction) => void;
}) {
  const translated = translateJobError(job.error, role, {
    errorCode: job.errorCode,
    stage,
  });
  if (!translated) return null;

  return (
    <div className="rounded-xl px-5 py-4 text-[13.5px] bg-status-error-soft border border-status-error/30 text-status-error shadow-sm">
      <p className="font-bold text-[15px] tracking-tight">{translated.title}</p>
      <p className="mt-1.5 font-medium leading-relaxed opacity-90">
        {translated.message}
      </p>
      {translated.actions.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2.5">
          {translated.actions.map((action) => {
            if (action.href?.startsWith("/") || action.href?.startsWith("#")) {
              if (action.href.startsWith("#")) {
                return (
                  <button
                    key={action.label}
                    type="button"
                    onClick={() => onAction?.(action)}
                    className="rounded-lg px-4 py-2 text-[12.5px] font-bold bg-panel border border-status-error/30 text-status-error hover:bg-panel-muted transition-colors shadow-sm"
                  >
                    {action.label}
                  </button>
                );
              }
              return (
                <Link
                  key={action.label}
                  href={action.href}
                  className="rounded-lg px-4 py-2 text-[12.5px] font-bold no-underline bg-panel border border-status-error/30 text-status-error hover:bg-panel-muted transition-colors shadow-sm"
                >
                  {action.label}
                </Link>
              );
            }
            return (
              <button
                key={action.label}
                type="button"
                onClick={() => onAction?.(action)}
                className="rounded-lg px-4 py-2 text-[12.5px] font-bold bg-panel border border-status-error/30 text-status-error hover:bg-panel-muted transition-colors shadow-sm"
              >
                {action.label}
              </button>
            );
          })}
        </div>
      )}
      {isAdminRole(role) && translated.technical && (
        <details className="mt-4">
          <summary className="cursor-pointer text-[12px] font-bold uppercase tracking-widest opacity-80 hover:opacity-100 transition-opacity outline-none">
            Technical details
          </summary>
          <pre className="mt-2.5 overflow-x-auto whitespace-pre-wrap rounded-lg p-3 text-[11px] font-mono bg-black/5 border border-black/10 text-status-error/90">
            {translated.technical}
          </pre>
        </details>
      )}
      {job.traceId ? (
        <p className="mt-3 font-mono text-[11px] text-status-error/80">
          trace: {job.traceId}
        </p>
      ) : null}
    </div>
  );
}
