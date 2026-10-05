import { FinishesPanel } from "@/components/settings/finishes-panel";
import { FrameDepthsPanel } from "@/components/settings/frame-depths-panel";
import { FrpConstantsPanel } from "@/components/settings/frp-constants-panel";
import { StockListsPanel } from "@/components/settings/reference-extra-panels";
import { SettingsPage, requireAdmin } from "@/components/settings/settings-page";

export const dynamic = "force-dynamic";

export default async function ReferenceSettingsPage() {
  await requireAdmin();
  return (
    <SettingsPage
      current="reference"
      description="The lookup tables matching and take-off read: finish codes, frame depths, FRP constants and the stock lists."
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <FinishesPanel />
        <FrameDepthsPanel />
      </div>
      <FrpConstantsPanel />
      <StockListsPanel />
    </SettingsPage>
  );
}
