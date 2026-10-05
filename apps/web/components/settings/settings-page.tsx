import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { PageHeader } from "@/components/shell/page-header";
import { SETTINGS_SECTIONS, SettingsTabs, type SettingsSection } from "@/components/settings/settings-tabs";

/** Admin-only settings pages send anyone else to the overview, which explains why. */
export async function requireAdmin(): Promise<void> {
  const session = await auth();
  if ((session?.user?.role ?? "estimator") !== "admin") redirect("/settings");
}

/**
 * One settings page: the header, the section tabs, then its panels. Header, tabs
 * and main are returned as siblings because the shell grid places each of them.
 */
export function SettingsPage({
  current,
  description,
  children,
}: {
  current: SettingsSection;
  description: string;
  children: React.ReactNode;
}) {
  const section = SETTINGS_SECTIONS.find((entry) => entry.key === current);
  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Workspace", href: "/dashboard" },
          { label: "Settings", href: "/settings" },
          { label: section?.label ?? "Settings" },
        ]}
      />
      <SettingsTabs current={current} />
      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="flex flex-col gap-4 w-full">
          <p className="text-[13.5px] font-medium text-tx-secondary">{description}</p>
          {children}
        </div>
      </main>
    </>
  );
}
