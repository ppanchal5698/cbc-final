"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FocusCard } from "@/components/shell/focus-card";
import {
  DiamondsFour,
  House,
  SquaresFour,
  Package,
  Books,
  SlidersHorizontal,
  WarningCircle,
  CurrencyDollar,
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

  return (
    <nav className="flex h-full w-[212px] shrink-0 flex-col border-r border-subtle bg-background">
      <div className="flex items-center gap-2.5 px-5 py-[18px]">
        <span className="grid h-7 w-7 place-items-center rounded-md bg-brand-soft text-brand-primary shadow-sm">
          <DiamondsFour size={17} weight="duotone" />
        </span>
        <span className="text-[15px] font-bold tracking-[0.02em] text-tx-primary">OPS·HUB</span>
      </div>

      <div className="flex flex-col gap-0.5 px-3">
        {NAV.map(({ href, label, Icon }) => {
          const active = pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-2.5 rounded-md px-3 py-2 text-[13px] font-medium no-underline transition-all duration-200",
                active
                  ? "bg-brand-soft text-brand-primary border border-brand-border shadow-sm"
                  : "text-tx-secondary border border-transparent hover:text-tx-primary hover:bg-panel-muted"
              )}
            >
              <Icon size={16} weight={active ? "fill" : "duotone"} className={cn("transition-colors", active ? "text-brand-primary" : "text-tx-muted group-hover:text-tx-secondary")} />
              <span className="flex-1">{label}</span>
              {href === "/price-books" && !!staleBooks && (
                <span className="tnum rounded-full bg-status-error-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-status-error shadow-sm">
                  {staleBooks}
                </span>
              )}
              {href === "/ops/dead-letter" && !!deadJobs && (
                <span className="tnum rounded-full bg-status-error-soft px-1.5 py-0.5 text-[10.5px] font-semibold text-status-error shadow-sm">
                  {deadJobs}
                </span>
              )}
            </Link>
          );
        })}
      </div>

      <div className="flex-1" />
      <div className="border-t border-subtle bg-background">
        <FocusCard user={user} />
      </div>
    </nav>
  );
}
