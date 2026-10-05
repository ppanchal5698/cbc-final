import { FinishesPanel } from "@/components/settings/finishes-panel";
import { FrameDepthsPanel } from "@/components/settings/frame-depths-panel";
import { FrpConstantsPanel } from "@/components/settings/frp-constants-panel";
import { StockListsPanel } from "@/components/settings/reference-extra-panels";
import { AdminPage, requireAdmin } from "@/components/shell/admin-page";

export const dynamic = "force-dynamic";

export default async function ReferenceDataPage() {
  await requireAdmin();
  return (
    <AdminPage
      crumbs={[{ label: "Reference data" }]}
      description="The lookup tables matching and take-off read: finish codes, frame depths, FRP constants and the stock lists."
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <FinishesPanel />
        <FrameDepthsPanel />
      </div>
      <FrpConstantsPanel />
      <StockListsPanel />
    </AdminPage>
  );
}
