import { ClaudeSettingsClient } from "@/components/settings/claude-settings";
import { ParsingSettingsClient } from "@/components/settings/parsing-settings";
import { SettingsPage, requireAdmin } from "@/components/settings/settings-page";

export const dynamic = "force-dynamic";

export default async function AiSettingsPage() {
  await requireAdmin();
  return (
    <SettingsPage
      current="ai"
      description="Which AI provider reads and prices bids, and which reader turns uploaded PDFs into page text."
    >
      <ClaudeSettingsClient />
      <ParsingSettingsClient />
    </SettingsPage>
  );
}
