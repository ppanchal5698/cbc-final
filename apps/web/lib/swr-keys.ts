/** Centralized SWR cache keys for consistent invalidation. */
export const swrKeys = {
  projects: (params?: { limit?: number; stage?: string; q?: string }) => {
    const search = new URLSearchParams();
    if (params?.limit) search.set("limit", String(params.limit));
    if (params?.stage) search.set("stage", params.stage);
    if (params?.q) search.set("q", params.q);
    const qs = search.toString();
    return `/api/proxy/projects${qs ? `?${qs}` : ""}`;
  },
  project: (code: string) => `/api/proxy/projects/${code}`,
  documents: (code: string) => `/api/proxy/projects/${code}/documents`,
  jobs: (code: string, limit = 12) =>
    `/api/proxy/jobs?project=${encodeURIComponent(code)}&limit=${limit}`,
  job: (id: string) => `/api/proxy/jobs/${id}`,
  lineItems: (code: string, filter?: string, alternate?: string | null) => {
    const search = new URLSearchParams();
    if (filter) search.set("filter", filter);
    if (alternate !== undefined && alternate !== null) search.set("alternate", alternate);
    const qs = search.toString();
    return `/api/proxy/projects/${code}/line-items${qs ? `?${qs}` : ""}`;
  },
  alternates: (code: string) => `/api/proxy/projects/${code}/alternates`,
  versions: (code: string) => `/api/proxy/projects/${code}/versions`,
  quote: (code: string) => `/api/proxy/projects/${code}/quote`,
  proposal: (code: string) => `/api/proxy/projects/${code}/proposal`,
  catalog: (params?: { q?: string; division?: string }) => {
    const search = new URLSearchParams();
    if (params?.q) search.set("q", params.q);
    if (params?.division) search.set("division", params.division);
    const qs = search.toString();
    return `/api/proxy/catalog/products${qs ? `?${qs}` : ""}`;
  },
  users: () => "/api/proxy/users",
  audit: (project?: string) =>
    project
      ? `/api/proxy/audit?limit=50&project=${encodeURIComponent(project)}`
      : "/api/proxy/audit?limit=50",
  pipelineSettings: () => "/api/proxy/settings/pipeline",
  freshnessSettings: () => "/api/proxy/settings/freshness",
  claudeSettings: () => "/api/proxy/settings/claude",
} as const;
