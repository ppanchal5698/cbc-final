import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { PageHeader } from "@/components/shell/page-header";

type Crumb = { label: string; href?: string };

/** An admin-only page sends anyone else to `fallback`. */
export async function requireAdmin(fallback = "/dashboard"): Promise<void> {
  const session = await auth();
  if ((session?.user?.role ?? "estimator") !== "admin") redirect(fallback);
}

/**
 * The frame every admin page shares: header, an optional bar (Settings' tabs), then
 * its panels. Returned as siblings because the shell grid places each of them.
 */
export function AdminPage({
  crumbs,
  description,
  bar,
  children,
}: {
  crumbs: Crumb[];
  description: string;
  bar?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace", href: "/dashboard" }, ...crumbs]} />
      {bar}
      <main id="main-content" className="min-h-0 flex-1 overflow-auto p-8 bg-background">
        <div className="flex flex-col gap-4 w-full">
          <p className="text-[13.5px] font-medium text-tx-secondary">{description}</p>
          {children}
        </div>
      </main>
    </>
  );
}
