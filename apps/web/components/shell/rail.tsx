"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FocusCard } from "@/components/shell/focus-card";
import { useUiState } from "@/components/shell/ui-state";
import {
  DiamondsFour,
  House,
  SquaresFour,
  Package,
  Books,
  SlidersHorizontal,
  WarningCircle,
  CurrencyDollar,
  SidebarSimple,
  CaretLeft,
  CaretRight,
} from "@phosphor-icons/react/dist/ssr";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/dashboard", label: "Dashboard", Icon: House },
  { href: "/bids", label: "Bid board", Icon: SquaresFour },
  { href: "/ops/dead-letter", label: "Dead letter", Icon: WarningCircle },
  { href: "/ops/spend", label: "Spend", Icon: CurrencyDollar },
  { href: "/catalog", label: "Product catalog", Icon: Package },
  { href: "/price-books", label: "Price books", Icon: Books },
  { href: "/settings", label: "Settings", Icon: SlidersHorizontal },
];

export function Rail({
  staleBooks,
  deadJobs,
  user,
}: {
  staleBooks?: number;
  deadJobs?: number;
  user: { name: string; initials: string };
}) {
  const pathname = usePathname();
  const { sidebarCollapsed, toggleSidebar } = useUiState();

  return (
    <nav
      aria-label="Main Navigation"
      className={cn(
        "relative flex h-full shrink-0 flex-col border-r border-subtle bg-background transition-[width] duration-300 ease-in-out select-none",
        sidebarCollapsed ? "w-[64px]" : "w-[212px]"
      )}
    >
      {/* Sidebar Header */}
      {sidebarCollapsed ? (
        <div className="flex flex-col items-center justify-center py-[14px] px-2 border-b border-subtle/40">
          <button
            type="button"
            onClick={toggleSidebar}
            title="Expand sidebar (Ctrl+B)"
            aria-label="Expand sidebar"
            className="group relative flex h-9 w-9 items-center justify-center rounded-lg bg-brand-soft text-brand-primary shadow-sm transition-all duration-200 hover:scale-105 hover:bg-brand-primary hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border"
          >
            <DiamondsFour size={19} weight="duotone" className="transition-transform group-hover:scale-110" />
            <span className="absolute -bottom-1 -right-1 grid h-4 w-4 place-items-center rounded-full bg-panel border border-subtle text-tx-secondary shadow-xs group-hover:bg-brand-primary group-hover:text-white group-hover:border-brand-primary transition-colors">
              <CaretRight size={9} weight="bold" />
            </span>
          </button>
        </div>
      ) : (
        <div className="flex items-center justify-between px-4 py-[15px] border-b border-subtle/40">
          <Link
            href="/dashboard"
            className="flex items-center gap-2.5 no-underline group focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border rounded-md"
          >
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-md bg-brand-soft text-brand-primary shadow-sm transition-transform duration-200 group-hover:scale-105">
              <DiamondsFour size={17} weight="duotone" />
            </span>
            <span className="text-[15px] font-bold tracking-[0.02em] text-tx-primary">
              OPS·HUB
            </span>
          </Link>

          <button
            type="button"
            onClick={toggleSidebar}
            title="Collapse sidebar (Ctrl+B)"
            aria-label="Collapse sidebar"
            className="grid h-7 w-7 place-items-center rounded-md text-tx-muted transition-colors hover:bg-panel-muted hover:text-tx-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border"
          >
            <SidebarSimple size={16} weight="duotone" />
          </button>
        </div>
      )}

      {/* Navigation items */}
      <div className={cn("flex flex-col gap-1 py-3 overflow-y-auto overflow-x-hidden", sidebarCollapsed ? "px-2" : "px-3")}>
        {NAV.map(({ href, label, Icon }) => {
          const active = pathname.startsWith(href);
          const badgeCount =
            href === "/price-books"
              ? staleBooks
              : href === "/ops/dead-letter"
                ? deadJobs
                : 0;

          if (sidebarCollapsed) {
            return (
              <Link
                key={href}
                href={href}
                title={badgeCount ? `${label} (${badgeCount})` : label}
                aria-label={label}
                className={cn(
                  "group relative flex h-10 w-10 items-center justify-center rounded-lg text-[13px] font-medium no-underline transition-all duration-200 mx-auto",
                  active
                    ? "bg-brand-soft text-brand-primary border border-brand-border shadow-sm"
                    : "text-tx-secondary border border-transparent hover:text-tx-primary hover:bg-panel-muted"
                )}
              >
                <Icon
                  size={19}
                  weight={active ? "fill" : "duotone"}
                  className={cn(
                    "transition-colors",
                    active ? "text-brand-primary" : "text-tx-muted group-hover:text-tx-secondary"
                  )}
                />
                {!!badgeCount && (
                  <span className="absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-status-error px-1 text-[9px] font-bold text-white shadow-sm ring-2 ring-background">
                    {badgeCount > 9 ? "9+" : badgeCount}
                  </span>
                )}
              </Link>
            );
          }

          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium no-underline transition-all duration-200",
                active
                  ? "bg-brand-soft text-brand-primary border border-brand-border shadow-sm font-semibold"
                  : "text-tx-secondary border border-transparent hover:text-tx-primary hover:bg-panel-muted"
              )}
            >
              <Icon
                size={16}
                weight={active ? "fill" : "duotone"}
                className={cn(
                  "shrink-0 transition-colors",
                  active ? "text-brand-primary" : "text-tx-muted group-hover:text-tx-secondary"
                )}
              />
              <span className="flex-1 truncate">{label}</span>
              {!!badgeCount && (
                <span className="tnum rounded-full bg-status-error-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-status-error shadow-sm">
                  {badgeCount}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      <div className="flex-1" />

      {/* Bottom User & Focus Section */}
      <div className="border-t border-subtle bg-background">
        <FocusCard user={user} collapsed={sidebarCollapsed} />

        {/* Bottom Toggle Bar */}
        {sidebarCollapsed ? (
          <div className="border-t border-subtle/50 py-2 flex justify-center">
            <button
              type="button"
              onClick={toggleSidebar}
              title="Expand sidebar (Ctrl+B)"
              aria-label="Expand sidebar"
              className="grid h-8 w-8 place-items-center rounded-lg text-tx-muted hover:bg-panel-muted hover:text-tx-primary transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border"
            >
              <SidebarSimple size={16} weight="duotone" />
            </button>
          </div>
        ) : (
          <div className="border-t border-subtle/50 px-3 py-2">
            <button
              type="button"
              onClick={toggleSidebar}
              title="Collapse sidebar (Ctrl+B)"
              aria-label="Collapse sidebar"
              className="flex items-center justify-between w-full rounded-md px-2 py-1.5 text-[12px] text-tx-muted hover:text-tx-primary hover:bg-panel-muted transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-border font-medium"
            >
              <span className="flex items-center gap-2">
                <CaretLeft size={14} weight="bold" />
                <span>Collapse sidebar</span>
              </span>
              <span className="rounded bg-panel-muted px-1.5 py-0.5 text-[10px] text-tx-muted border border-subtle font-mono">
                Ctrl+B
              </span>
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
