/** Typed API path builders for the authenticated proxy. */

export const endpoints = {
  jobCancel: (jobId: string) => `/api/proxy/jobs/${jobId}/cancel`,
  jobRetry: (jobId: string) => `/api/proxy/jobs/${jobId}/retry`,
  jobsDead: () => "/api/proxy/jobs/dead",
  pipelineSettings: () => "/api/proxy/settings/pipeline",
  freshnessSettings: () => "/api/proxy/settings/freshness",
  integrations: () => "/api/proxy/integrations",
  projectDelete: (code: string) => `/api/proxy/projects/${encodeURIComponent(code)}`,
  proposalPdf: (code: string) => `/api/proxy/projects/${code}/proposal/pdf`,
  proposalRender: (code: string) => `/api/proxy/projects/${code}/proposal/render`,
  jobTerminal: (jobId: string) => `/api/proxy/jobs/${jobId}/terminal`,
  claudeOauthCode: () => "/api/proxy/settings/claude/oauth/code",
  jobMetrics: (hours = 24) => `/api/proxy/jobs/metrics?hours=${hours}`,
  opsSpend: (hours = 24) => `/api/proxy/ops/spend?hours=${hours}`,
  referenceMargins: () => "/api/proxy/reference/margins",
  referenceTax: () => "/api/proxy/reference/tax",
  referenceVendorTiers: () => "/api/proxy/reference/vendor-tiers",
  referenceSpecialNets: () => "/api/proxy/reference/special-nets",
  referenceLiteKit: () => "/api/proxy/reference/lite-kit",
  referenceStock: (vendor: string) => `/api/proxy/reference/stock/${encodeURIComponent(vendor)}`,
  referenceCustomOther: () => "/api/proxy/reference/custom-other-matrix",
} as const;
