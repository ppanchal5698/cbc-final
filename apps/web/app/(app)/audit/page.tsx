import { AuditLogPanel } from "@/components/settings/admin-panels";
import { AdminPage, requireAdmin } from "@/components/shell/admin-page";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  await requireAdmin();
  return (
    <AdminPage crumbs={[{ label: "Audit log" }]} description="Every change made in the app: who, what and when.">
      <AuditLogPanel />
    </AdminPage>
  );
}
