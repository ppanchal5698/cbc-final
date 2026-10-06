import { UsersAdminPanel } from "@/components/settings/admin-panels";
import { AdminPage, requireAdmin } from "@/components/shell/admin-page";

export const dynamic = "force-dynamic";

export default async function UsersPage() {
  await requireAdmin();
  return (
    <AdminPage crumbs={[{ label: "Users" }]} description="Who can sign in, and with which role.">
      <UsersAdminPanel />
    </AdminPage>
  );
}
