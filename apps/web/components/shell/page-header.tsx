import { auth } from "@/auth";
import { Header, type Crumb } from "@/components/shell/header";

/** Server wrapper that feeds the signed-in user into the client header. */
export async function PageHeader({
  crumbs,
  runPill,
  reviewCount,
  code,
}: {
  crumbs: Crumb[];
  runPill?: { label: string; tone: "running" | "done" | "failed" } | null;
  reviewCount?: number;
  code?: string | null;
}) {
  const session = await auth();
  const user = {
    name: session?.user?.name ?? "Estimator",
    initials:
      (session?.user as { initials?: string } | undefined)?.initials ??
      (session?.user?.name ?? "E")
        .split(" ")
        .map((part) => part[0])
        .slice(0, 2)
        .join("")
        .toUpperCase(),
    role: session?.user?.role ?? "estimator",
  };

  return (
    <Header
      crumbs={crumbs}
      user={user}
      runPill={runPill}
      reviewCount={reviewCount}
      code={code}
    />
  );
}
