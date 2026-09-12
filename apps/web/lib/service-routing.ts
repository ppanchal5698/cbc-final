/**
 * Map /api/... path segments to the upstream FastAPI host.
 *
 * All domain HTTP now lives on the modular monolith (`platform`). The browser
 * still talks to same-origin `/api/proxy/...`; this module picks the base URL
 * and JWT audience (always platform).
 */

const PLATFORM =
  process.env.PLATFORM_URL ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8001";

export type ServiceAudience = "platform";

/** First path segment after `/api/` (proxy strips that prefix already). */
export function resolveServiceBase(_path: string[]): string {
  return PLATFORM;
}

/** Audience claim for the upstream service (always the monolith). */
export function resolveServiceAudience(_path: string[]): ServiceAudience {
  return "platform";
}

export const SERVICE_URLS = {
  platform: PLATFORM,
} as const;
