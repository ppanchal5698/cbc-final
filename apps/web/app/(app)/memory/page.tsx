import { MemoryClient } from "@/components/memory/memory-client";
import { AdminPage, requireAdmin } from "@/components/shell/admin-page";

export const dynamic = "force-dynamic";

export default async function MemoryPage() {
  await requireAdmin();
  return (
    <AdminPage
      crumbs={[{ label: "Memory graph" }]}
      description="Vendors, multipliers, customers, catalog items and reference data, connected - and every approved bid the system has learned from."
    >
      <MemoryClient />
    </AdminPage>
  );
}
