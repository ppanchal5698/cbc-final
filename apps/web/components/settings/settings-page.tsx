import { AdminPage, requireAdmin as requireAdminOr } from "@/components/shell/admin-page";
import { SETTINGS_SECTIONS, SettingsTabs, type SettingsSection } from "@/components/settings/settings-tabs";

/** A settings section sends a non-admin to the Settings overview, which explains why. */
export function requireAdmin(): Promise<void> {
  return requireAdminOr("/settings");
}

/** One settings section: the shared admin frame with the section tabs as its bar. */
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
    <AdminPage
      crumbs={[{ label: "Settings", href: "/settings" }, { label: section?.label ?? "Settings" }]}
      description={description}
      bar={<SettingsTabs current={current} />}
    >
      {children}
    </AdminPage>
  );
}
