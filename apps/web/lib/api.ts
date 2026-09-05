/**
 * Thin client for the FastAPI service.
 *
 * The API owns every business rule and all Mongo writes; this file only moves
 * JSON. Nothing here computes a price, a margin or a total - that lives in
 * calc-engine, behind the API, so the numbers on a quote have one implementation.
 */

import "server-only";

import { auth } from "@/auth";
import { internalApiHeaders } from "@/lib/internal-api";
import { formatApiDetail } from "@/lib/format";
import { resolveServiceAudience, resolveServiceBase } from "@/lib/service-routing";

/** @deprecated Prefer resolveServiceBase; kept for health/fallback messages. */
export const API_BASE = process.env.PLATFORM_URL ?? process.env.API_BASE_URL ?? "http://127.0.0.1:8001";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Options = RequestInit & { actor?: string };

function resolveUrl(path: string): { url: URL; base: string; audience: ReturnType<typeof resolveServiceAudience> } {
  if (path.startsWith("http")) {
    return { url: new URL(path), base: path, audience: "platform" };
  }
  const trimmed = path.replace(/^\/api\//, "").replace(/^\//, "");
  const segments = trimmed.split("/").filter(Boolean);
  const base = resolveServiceBase(segments);
  return {
    url: new URL(`${base}/api/${segments.join("/")}`),
    base,
    audience: resolveServiceAudience(segments),
  };
}

async function request<T>(path: string, options: Options = {}): Promise<T> {
  const { actor, ...init } = options;
  const { url, base, audience } = resolveUrl(path);

  let resolvedActor = actor;
  if (!resolvedActor) {
    const session = await auth();
    resolvedActor = session?.user?.email ?? undefined;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        ...(init.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(await internalApiHeaders(resolvedActor, audience)),
        ...init.headers,
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${base}. Start domain services via docker compose -f infra/docker-compose.yml up`,
      503,
    );
  }

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(formatApiDetail(detail, response.statusText), response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown, actor?: string) =>
    request<T>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined, actor }),
  patch: <T>(path: string, body: unknown, actor?: string) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body), actor }),
  del: <T>(path: string, actor?: string) => request<T>(path, { method: "DELETE", actor }),
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: "POST", body: form }),
};
