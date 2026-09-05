"use client";

import { useEffect } from "react";
import Link from "next/link";
import { ArrowClockwise, WarningOctagon } from "@phosphor-icons/react/dist/ssr";

/**
 * The boundary for the whole signed-in shell.
 *
 * The bid pages re-throw anything that is not a 404, and before this existed
 * that meant Next's default error screen: no wording from the API, no way back,
 * and no retry. `retry` re-runs the failed segment on the server, which is what
 * an estimator wants when the API was simply restarting.
 *
 * Next 16 passes `retry`, not `reset` - see
 * node_modules/next/dist/docs/01-app/03-api-reference/03-file-conventions/error.md
 */
export default function AppError({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error("Ops-Hub page error:", error);
  }, [error]);

  return (
    <main className="grid flex-1 place-items-center p-6 bg-background">
      <div className="grid max-w-[520px] justify-items-center gap-3 text-center">
        <span className="grid h-11 w-11 place-items-center rounded-xl bg-status-error-soft text-status-error shadow-sm">
          <WarningOctagon size={22} weight="duotone" />
        </span>

        <h1 className="text-[17px] font-semibold text-tx-primary">This screen could not be loaded</h1>

        <p className="text-[13px] leading-relaxed text-tx-secondary font-medium">
          {/* The API's own message, which is usually the actionable part - it
              names the host when the service is simply not running. */}
          {error.message || "Something went wrong while reading this bid."}
        </p>

        <div className="mt-2 flex flex-wrap justify-center gap-2">
          <button
            onClick={retry}
            className="flex items-center gap-1.5 rounded-md px-3.5 py-2 text-[12.5px] font-semibold bg-brand-primary text-white shadow-sm hover:bg-brand-primary/90 transition-colors"
          >
            <ArrowClockwise size={14} weight="bold" />
            Try again
          </button>
          <Link
            href="/dashboard"
            className="rounded-md px-3.5 py-2 text-[12.5px] font-medium no-underline border border-subtle bg-panel text-tx-secondary hover:text-tx-primary hover:bg-panel-muted transition-colors shadow-sm"
          >
            Back to the dashboard
          </Link>
        </div>

        {error.digest && (
          <p className="mt-2 text-[11px] text-tx-muted font-medium">
            Reference <span className="font-mono bg-panel-muted px-1 py-0.5 rounded border border-subtle">{error.digest}</span> — quote this if you report it.
          </p>
        )}

        <p className="mt-1 text-[11.5px] text-tx-muted">
          Nothing was sent and nothing was lost. Work already saved against this bid is untouched.
        </p>
      </div>
    </main>
  );
}
