/**
 * Thin server-side client for the platform API.
 *
 * The API owns every business rule and all Mongo writes; this file only moves
 * JSON. Nothing here computes a price, a margin or a total - that lives behind
 * the API, so the numbers on a quote have one implementation. Server components
 * only read; every write goes through the authenticated proxy.
 */

import "server-only";

import { auth } from "@/auth";
import { internalApiHeaders } from "@/lib/internal-api";
import { formatApiDetail } from "@/lib/format";

/** The one backend: the modular monolith, compose service `platform`. */
export const PLATFORM_URL = process.env.PLATFORM_URL ?? "http://127.0.0.1:8001";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function get<T>(path: string): Promise<T> {
  const url = path.startsWith("http")
    ? new URL(path)
    : new URL(`${PLATFORM_URL}/api/${path.replace(/^\/api\//, "").replace(/^\//, "")}`);
  const session = await auth();

  let response: Response;
  try {
    response = await fetch(url, {
      headers: await internalApiHeaders(session?.user?.email),
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      `Cannot reach the API at ${PLATFORM_URL}. Start the stack with docker compose up -d`,
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

export const api = { get };
