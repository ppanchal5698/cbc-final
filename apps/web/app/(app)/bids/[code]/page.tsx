import { redirect } from "next/navigation";

import { api } from "@/lib/api";
import type { Project } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Land on whichever stage the bid has reached. */
export default async function BidRoot({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  const project = await api.get<Project>(`/api/projects/${code}`).catch(() => null);
  redirect(`/bids/${code}/${project?.stage ?? "intake"}`);
}
