import { MagnifyingGlass } from "@phosphor-icons/react/dist/ssr";

import { NotFoundView } from "@/components/shell/not-found-view";

/**
 * All four bid stages call notFound() on a 404 from the API. Until this file
 * existed that produced the stock Next 404, which says nothing about bids.
 */
export default function BidNotFound() {
  return (
    <NotFoundView
      icon={<MagnifyingGlass size={22} weight="duotone" />}
      title="No such bid"
      body="That bid number is not on this installation. It may have been removed, or the link may have been typed by hand."
      primaryHref="/bids"
      primaryLabel="Open the bid board"
      secondaryHref="/dashboard"
      secondaryLabel="Back to the dashboard"
    />
  );
}
