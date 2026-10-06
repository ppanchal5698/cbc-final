import { AddersPanel } from "@/components/settings/adders-panel";
import { CustomOtherMatrixPanel } from "@/components/settings/custom-other-matrix-panel";
import { LiteKitPanel } from "@/components/settings/lite-kit-panel";
import { MarginFrameworkPanel } from "@/components/settings/margin-framework-panel";
import { HardwareEqualsPanel, SpecialNetsPanel } from "@/components/settings/reference-extra-panels";
import { SpecialMarginsPanel } from "@/components/settings/special-margins-panel";
import { TaxRatesPanel } from "@/components/settings/tax-rates-panel";
import { VendorTiersPanel } from "@/components/settings/vendor-tiers-panel";
import { AdminPage, requireAdmin } from "@/components/shell/admin-page";

export const dynamic = "force-dynamic";

export default async function PricingPage() {
  await requireAdmin();
  return (
    <AdminPage
      crumbs={[{ label: "Pricing" }]}
      description="The numbers a quote is priced with: margins, tax, vendor multipliers, special nets, adders and the Allegion equals."
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <MarginFrameworkPanel />
        <SpecialMarginsPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <VendorTiersPanel />
        <SpecialNetsPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <TaxRatesPanel />
        <AddersPanel />
      </div>
      <HardwareEqualsPanel />
      <LiteKitPanel />
      <CustomOtherMatrixPanel />
    </AdminPage>
  );
}
