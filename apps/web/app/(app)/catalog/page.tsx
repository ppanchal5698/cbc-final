import { CatalogClient } from "@/components/catalog/catalog-client";
import { PageHeader } from "@/components/shell/page-header";

export const dynamic = "force-dynamic";

export default async function CatalogPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string }>;
}) {
  const { q } = await searchParams;
  return (
    <>
      <PageHeader crumbs={[{ label: "Workspace", href: "/dashboard" }, { label: "Product catalog" }]} />
      <CatalogClient initialQuery={q ?? ""} />
    </>
  );
}
