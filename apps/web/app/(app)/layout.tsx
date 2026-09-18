import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { Rail } from "@/components/shell/rail";
import { ShellOverlays } from "@/components/shell/shell-overlays";
import { UiStateProvider } from "@/components/shell/ui-state";
import { api } from "@/lib/api";
import { userInitials } from "@/lib/initials";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user) redirect("/signin");

  const user = {
    name: session.user.name ?? "Estimator",
    initials: userInitials(session.user.name, session.user.initials),
    role: session.user.role ?? "estimator",
  };

  // A stale price book is a live risk to every quote, so the count rides the nav.
  let staleBooks = 0;
  let deadJobs = 0;
  try {
    const books = await api.get<{ counts: { stale: number } }>("/api/price-books");
    staleBooks = books.counts.stale;
  } catch {
    /* the API being down is surfaced on the page itself, not here */
  }
  try {
    const dead = await api.get<{ total: number }>("/api/jobs/dead");
    deadJobs = dead.total;
  } catch {
    /* same: the dead-letter page reports the outage */
  }

  return (
    <UiStateProvider userRole={user.role}>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-panel focus:px-3 focus:py-2 focus:text-[13px] focus:shadow-lg"
      >
        Skip to main content
      </a>
      <div className="flex h-screen overflow-hidden">
        <Rail staleBooks={staleBooks} deadJobs={deadJobs} user={user} />
        <div className="flex min-w-0 flex-1 flex-col">{children}</div>
      </div>
      <ShellOverlays />
    </UiStateProvider>
  );
}
