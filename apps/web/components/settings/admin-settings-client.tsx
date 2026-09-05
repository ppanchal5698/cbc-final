"use client";

import {
  AuditLogPanel,
  IntegrationsPanel,
  PipelineSettingsPanel,
  FreshnessSettingsPanel,
  UsersAdminPanel,
} from "@/components/settings/admin-panels";
import { MarginFrameworkPanel } from "@/components/settings/margin-framework-panel";
import { TaxRatesPanel } from "@/components/settings/tax-rates-panel";
import { AddersPanel } from "@/components/settings/adders-panel";
import { SpecialMarginsPanel } from "@/components/settings/special-margins-panel";
import { FinishesPanel } from "@/components/settings/finishes-panel";
import { FrameDepthsPanel } from "@/components/settings/frame-depths-panel";
import { FrpConstantsPanel } from "@/components/settings/frp-constants-panel";
import { QueueMetricsPanel } from "@/components/settings/queue-metrics-panel";
import {
  CustomOtherMatrixPanel,
  LiteKitPanel,
  SpecialNetsPanel,
  StockListsPanel,
  VendorTiersPanel,
} from "@/components/settings/reference-extra-panels";

export function AdminSettingsClient() {
  return (
    <div className="flex flex-col gap-4">
      <QueueMetricsPanel />
      <IntegrationsPanel />
      <PipelineSettingsPanel />
      <FreshnessSettingsPanel />
      <div className="grid gap-4 xl:grid-cols-2">
        <MarginFrameworkPanel />
        <TaxRatesPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <AddersPanel />
        <SpecialMarginsPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <FinishesPanel />
        <FrameDepthsPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <FrpConstantsPanel />
        <VendorTiersPanel />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <SpecialNetsPanel />
        <LiteKitPanel />
      </div>
      <StockListsPanel />
      <CustomOtherMatrixPanel />
      <div className="grid gap-4 xl:grid-cols-2">
        <UsersAdminPanel />
      </div>
      <AuditLogPanel />
    </div>
  );
}
