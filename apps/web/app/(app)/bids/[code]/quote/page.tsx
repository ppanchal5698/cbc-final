import { notFound } from "next/navigation";

import { QuoteClient } from "@/components/quote/quote-client";
import { PageHeader } from "@/components/shell/page-header";
import { runPillFor } from "@/lib/run-pill";
import { StageBar } from "@/components/shell/stage-bar";
import { ApiError, api } from "@/lib/api";
import type { Job, Project } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function QuotePage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;

  let project: Project;
  try {
    project = await api.get<Project>(`/api/projects/${code}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const jobs = (
    await api.get<{ jobs: Job[] }>(`/api/jobs?project=${code}&limit=1`)
  ).jobs;

  return (
    <>
      <PageHeader
        crumbs={[{ label: "Workspace", href: "/dashboard" }, { label: `${project.code} · Quote` }]}
        runPill={runPillFor(jobs[0], project.counts.total, project.phase, project.chainState)}
        reviewCount={project.counts.needsLook}
        code={project.code}
      />
      <StageBar project={project} current="quote" />
      <QuoteClient code={project.code} initialJob={jobs[0] ?? null} autopilot={Boolean(project.autopilot)} />
    </>
  );
}
