import { notFound } from "next/navigation";

import { ExtractionClient } from "@/components/extraction/extraction-client";
import { PageHeader } from "@/components/shell/page-header";
import { runPillFor } from "@/lib/run-pill";
import { StageBar } from "@/components/shell/stage-bar";
import { ApiError, api } from "@/lib/api";
import type { BidDocument, Job, Project } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function ExtractionPage({
  params,
}: {
  params: Promise<{ code: string }>;
}) {
  const { code } = await params;

  let project: Project;
  try {
    project = await api.get<Project>(`/api/projects/${code}`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) notFound();
    throw error;
  }

  const [documents, jobs] = await Promise.all([
    api
      .get<{ documents: BidDocument[] }>(`/api/projects/${code}/documents`)
      .then((r) => r.documents),
    api
      .get<{ jobs: Job[] }>(`/api/jobs?project=${code}&limit=1`)
      .then((r) => r.jobs),
  ]);

  return (
    <>
      <PageHeader
        crumbs={[
          { label: "Workspace", href: "/dashboard" },
          { label: `${project.code} · Extraction & entry` },
        ]}
        runPill={runPillFor(jobs[0], project.counts.total, project.phase, project.chainState)}
        reviewCount={project.counts.needsLook}
        code={project.code}
      />
      <StageBar project={project} current="extraction" />
      <ExtractionClient
        code={project.code}
        documents={documents}
        initialJob={jobs[0] ?? null}
        autopilot={Boolean(project.autopilot)}
      />
    </>
  );
}
