/** Typed API path builders for the authenticated proxy. */

export const endpoints = {
  jobCancel: (jobId: string) => `/api/proxy/jobs/${jobId}/cancel`,
  jobRetry: (jobId: string) => `/api/proxy/jobs/${jobId}/retry`,
  pipelineSettings: () => "/api/proxy/settings/pipeline",
  freshnessSettings: () => "/api/proxy/settings/freshness",
  integrations: () => "/api/proxy/integrations",
  projectDelete: (code: string) => `/api/proxy/projects/${encodeURIComponent(code)}`,
  proposalPdf: (code: string) => `/api/proxy/projects/${code}/proposal/pdf`,
  jobTerminal: (jobId: string) => `/api/proxy/jobs/${jobId}/terminal`,
  claudeOauthCode: () => "/api/proxy/settings/claude/oauth/code",
  parsingSettings: () => "/api/proxy/settings/parsing",
  parsingSettingsTest: () => "/api/proxy/settings/parsing/test",
  documentPageBlocks: (code: string, documentId: string, page: number) =>
    `/api/proxy/projects/${encodeURIComponent(code)}/documents/${documentId}/pages/${page}/blocks`,
  jobMetrics: (hours = 24) => `/api/proxy/jobs/metrics?hours=${hours}`,
  opsSpend: (hours = 24) => `/api/proxy/ops/spend?hours=${hours}`,
  opsCohorts: (days = 30, limit = 20) =>
    `/api/proxy/ops/cohorts?days=${days}&limit=${limit}`,
} as const;
