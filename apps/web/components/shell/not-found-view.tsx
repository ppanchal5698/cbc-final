import Link from "next/link";
import type { ReactNode } from "react";

/**
 * Shared empty-state layout for not-found pages inside the app shell.
 * Bid-specific and global 404s both use this so CTAs and typography stay aligned.
 */
export function NotFoundView({
  icon,
  title,
  body,
  primaryHref,
  primaryLabel,
  secondaryHref,
  secondaryLabel,
}: {
  icon: ReactNode;
  title: string;
  body: string;
  primaryHref: string;
  primaryLabel: string;
  secondaryHref: string;
  secondaryLabel: string;
}) {
  return (
    <main className="grid flex-1 place-items-center p-8 bg-background">
      <div className="grid max-w-[460px] justify-items-center gap-4 text-center">
        <span className="grid h-16 w-16 place-items-center rounded-2xl bg-panel-muted border border-subtle text-tx-muted shadow-sm">
          {icon}
        </span>

        <h1 className="text-[20px] font-bold text-tx-primary tracking-tight mt-2">{title}</h1>

        <p className="text-[14px] font-medium leading-relaxed text-tx-secondary">
          {body}
        </p>

        <div className="mt-4 flex flex-wrap justify-center gap-3">
          <Link
            href={primaryHref}
            className="rounded-md px-5 py-2.5 text-[13px] font-bold no-underline bg-brand-primary text-white hover:bg-brand-primary/90 transition-colors shadow-sm"
          >
            {primaryLabel}
          </Link>
          <Link
            href={secondaryHref}
            className="rounded-md px-5 py-2.5 text-[13px] font-bold no-underline border border-subtle bg-panel text-tx-secondary hover:bg-panel-muted transition-colors shadow-sm"
          >
            {secondaryLabel}
          </Link>
        </div>
      </div>
    </main>
  );
}
