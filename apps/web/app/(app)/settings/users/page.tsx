import { AuditLogPanel, UsersAdminPanel } from "@/components/settings/admin-panels";
import { SettingsPage, requireAdmin } from "@/components/settings/settings-page";

export const dynamic = "force-dynamic";

export default async function UsersSettingsPage() {
  await requireAdmin();
  return (
    <SettingsPage current="users" description="Who can sign in and with which role, and every change made in the app.">
      <UsersAdminPanel />
      <AuditLogPanel />
    </SettingsPage>
  );
}
