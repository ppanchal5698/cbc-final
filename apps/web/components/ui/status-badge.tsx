import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

const VARIANTS = {
  action: "text-brand-primary bg-brand-soft border-brand-border",
  review: "text-status-error bg-status-error-soft border-status-error/30",
  progress: "text-status-warning bg-status-warning-soft border-status-warning/30",
  ok: "text-status-success bg-status-success-soft border-transparent",
  caution: "text-status-warning bg-transparent border-status-warning/30",
  neutral: "text-tx-muted bg-panel-muted border-transparent",
} as const;

export type StatusBadgeVariant = keyof typeof VARIANTS;

export function StatusBadge({
  variant,
  children,
  className = "",
  dashed = false,
}: {
  variant: StatusBadgeVariant;
  children: ReactNode;
  className?: string;
  dashed?: boolean;
}) {
  const variantClass = VARIANTS[variant];
  return (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[10.5px] font-medium border shadow-sm",
        variantClass,
        dashed ? "border-dashed" : "border-solid",
        className
      )}
    >
      {children}
    </span>
  );
}

export function statusBadgeVariantForQueueTag(tag: string): StatusBadgeVariant {
  if (tag.includes("Claude") || tag.includes("reading")) return "progress";
  if (tag.includes("to check")) return "review";
  if (tag.includes("Ready to hand off")) return "ok";
  if (tag.includes("Ready to price")) return "action";
  return "neutral";
}
