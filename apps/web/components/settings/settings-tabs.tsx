import Link from "next/link";
import { Brain, Gauge } from "@phosphor-icons/react/dist/ssr";

export type SettingsSection = "ai" | "pipeline";

export const SETTINGS_SECTIONS: {
  key: SettingsSection;
  label: string;
  hint: string;
  Icon: typeof Brain;
}[] = [
  { key: "ai", label: "AI & reading", hint: "Provider and bid-set reader", Icon: Brain },
  { key: "pipeline", label: "Pipeline", hint: "Defaults, freshness, queue", Icon: Gauge },
];

/**
 * The settings sub-navigation. Sits in the shell's stage-bar row, like a bid's
 * stages. A `div` with the navigation role, not a `<nav>`: `.app-shell > nav` is
 * the rail's grid slot, and a direct `<nav>` child would be drawn there.
 */
export function SettingsTabs({ current }: { current: SettingsSection }) {
  return (
    <div
      role="navigation"
      aria-label="Settings sections"
      className="flex shrink-0 items-center gap-3 border-b border-subtle bg-panel-raised px-5 py-3 overflow-x-auto min-w-0"
    >
      {SETTINGS_SECTIONS.map(({ key, label, hint, Icon }) => {
        const active = key === current;
        return (
          <Link
            key={key}
            href={`/settings/${key}`}
            aria-current={active ? "page" : undefined}
            className={`flex min-w-[220px] max-w-[320px] flex-1 items-center gap-3 rounded-xl px-4 py-2.5 no-underline transition-all shadow-sm ${
              active
                ? "bg-brand-primary/10 border border-brand-primary/20"
                : "bg-panel border border-subtle hover:bg-panel-muted hover:border-brand-border"
            }`}
          >
            <span
              className={`grid h-[28px] w-[28px] shrink-0 place-items-center rounded-lg shadow-sm ${
                active
                  ? "bg-brand-primary text-white border border-brand-primary/20"
                  : "bg-panel-muted text-tx-muted border border-subtle"
              }`}
            >
              <Icon size={16} weight={active ? "fill" : "duotone"} />
            </span>
            <span className="flex min-w-0 flex-col leading-tight">
              <span className={`truncate text-[13px] font-bold ${active ? "text-brand-primary" : "text-tx-primary"}`}>
                {label}
              </span>
              <span className="truncate text-[11px] font-medium text-tx-muted mt-0.5">{hint}</span>
            </span>
          </Link>
        );
      })}
    </div>
  );
}
