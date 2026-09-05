import { ClaudeSettingsClient } from "@/components/settings/claude-settings";
import { AdminSettingsClient } from "@/components/settings/admin-settings-client";
import { IntegrationsPanel } from "@/components/settings/admin-panels";
import { PageHeader } from "@/components/shell/page-header";
import { auth } from "@/auth";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  const session = await auth();
  const role = session?.user?.role ?? "estimator";
  const isAdmin = role === "admin";

  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace", href: "/dashboard" }, { label: "Settings" }]} />
      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="flex flex-col gap-6 w-full">
        {isAdmin ? (
          <>
            <section className="rounded-xl px-6 py-5 bg-panel border border-subtle shadow-sm">
              <h2 className="text-[18px] font-bold text-tx-primary tracking-tight">Administration</h2>
              <p className="mt-1.5 text-[13.5px] font-medium text-tx-secondary">
                Configure the AI provider, pipeline defaults, user accounts, and review the audit log.
              </p>
            </section>
            <ClaudeSettingsClient />
            <AdminSettingsClient />
          </>
        ) : (
          <>
            <IntegrationsPanel />
            <section className="rounded-xl p-8 bg-panel border border-subtle shadow-sm">
              <h2 className="text-[18px] font-bold text-tx-primary tracking-tight">Automation status</h2>
              <p className="mt-3 text-[13.5px] font-medium text-tx-secondary leading-relaxed max-w-3xl">
                Your administrator configures the AI provider that reads bid documents and prices lines.
                If automatic reads fail, add lines by hand or ask your admin to check Settings.
              </p>
              <p className="mt-4 text-[12.5px] font-medium text-tx-muted">
                Provider configuration and user administration are limited to administrators.
              </p>
            </section>
          </>
        )}
        </div>
      </main>
    </>
  );
}
