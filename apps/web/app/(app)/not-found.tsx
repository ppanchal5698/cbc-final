import { MapTrifold } from "@phosphor-icons/react/dist/ssr";

import { NotFoundView } from "@/components/shell/not-found-view";

/** Branded 404 for unknown routes inside the authenticated app shell. */
export default function AppNotFound() {
  return (
    <NotFoundView
      icon={<MapTrifold size={22} weight="duotone" />}
      title="Page not found"
      body="That address is not part of Ops-Hub. The link may be outdated, or the URL may have been mistyped."
      primaryHref="/dashboard"
      primaryLabel="Back to the dashboard"
      secondaryHref="/bids"
      secondaryLabel="Open the bid board"
    />
  );
}
