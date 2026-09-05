import type { ReactNode } from "react";

export function StagePanel({
  icon,
  title,
  subtitle,
  actions,
}: {
  icon: ReactNode;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4 rounded-xl px-5 py-4 bg-panel border border-subtle shadow-sm">
      <div className="flex min-w-0 items-start gap-4">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-brand-primary/10 text-brand-primary border border-brand-primary/20 shadow-sm">
          {icon}
        </span>
        <span className="flex min-w-0 flex-col justify-center">
          <span className="text-[16px] font-bold text-tx-primary tracking-tight">{title}</span>
          {subtitle ? (
            <span className="text-[13px] font-medium text-tx-secondary mt-0.5">
              {subtitle}
            </span>
          ) : null}
        </span>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
