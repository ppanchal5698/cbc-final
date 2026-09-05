/**
 * Map /api/... path segments to the owning domain service base URL.
 *
 * The browser still talks to same-origin `/api/proxy/...`; this module picks
 * which FastAPI service receives the upstream call.
 */

const PLATFORM =
  process.env.PLATFORM_URL ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8001";
const INTAKE = process.env.INTAKE_URL ?? PLATFORM;
const EXTRACTION = process.env.EXTRACTION_URL ?? PLATFORM;
const PRICING = process.env.PRICING_URL ?? PLATFORM;
const QUOTING = process.env.QUOTING_URL ?? PLATFORM;
const CATALOG = process.env.CATALOG_URL ?? PLATFORM;

export type ServiceAudience =
  | "platform"
  | "intake"
  | "extraction"
  | "pricing"
  | "quoting"
  | "catalog";

/** First path segment after `/api/` (proxy strips that prefix already). */
export function resolveServiceBase(path: string[]): string {
  return SERVICE_URLS[resolveServiceAudience(path)];
}

/** Audience claim for the upstream service that owns this path. */
export function resolveServiceAudience(path: string[]): ServiceAudience {
  const head = path[0] ?? "";

  if (
    head === "auth" ||
    head === "users" ||
    head === "jobs" ||
    head === "settings" ||
    head === "audit" ||
    head === "calls" ||
    head === "integrations" ||
    head === "ops" ||
    head === "health"
  ) {
    return "platform";
  }

  if (head === "catalog" || head === "price-books") {
    return "catalog";
  }

  if (head === "reference") {
    return "pricing";
  }

  if (head === "projects") {
    if (path.length < 3) {
      return "platform";
    }
    const resource = path[2] ?? "";
    switch (resource) {
      case "documents":
      case "versions":
        return "intake";
      case "line-items":
      case "alternates":
        return "extraction";
      case "quote":
      case "proposal":
        return "quoting";
      case "calls":
        return "platform";
      default:
        return "platform";
    }
  }

  return "platform";
}

export const SERVICE_URLS = {
  platform: PLATFORM,
  intake: INTAKE,
  extraction: EXTRACTION,
  pricing: PRICING,
  quoting: QUOTING,
  catalog: CATALOG,
} as const;
