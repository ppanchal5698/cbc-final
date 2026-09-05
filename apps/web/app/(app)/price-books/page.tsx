import { PriceBooksClient } from "@/components/price-books/price-books-client";
import { PageHeader } from "@/components/shell/page-header";

export const dynamic = "force-dynamic";

export default function PriceBooksPage() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace", href: "/dashboard" }, { label: "Price books" }]} />
      <PriceBooksClient />
    </>
  );
}
