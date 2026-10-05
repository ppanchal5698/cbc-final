import {
  FreshnessSettingsPanel,
  IntegrationsPanel,
  PipelineSettingsPanel,
} from "@/components/settings/admin-panels";
import { QueueMetricsPanel } from "@/components/settings/queue-metrics-panel";
import { SettingsPage, requireAdmin } from "@/components/settings/settings-page";

export const dynamic = "force-dynamic";

export default async function PipelineSettingsPage() {
  await requireAdmin();
  return (
    <SettingsPage
      current="pipeline"
      description="How a new bid runs, when a price book counts as stale, and how the job queue and connected systems are doing."
    >
      <div className="grid gap-4 xl:grid-cols-2">
        <PipelineSettingsPanel />
        <FreshnessSettingsPanel />
      </div>
      <QueueMetricsPanel />
      <IntegrationsPanel />
    </SettingsPage>
  );
}
