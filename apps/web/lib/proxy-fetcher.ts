/** Browser-side fetch helpers for the authenticated API proxy. */
import { formatApiDetail } from "@/lib/format";

/**
 * Same-origin URL for a document the browser fetches directly (the PDF viewer).
 *
 * Deliberately here rather than in lib/api.ts: that module is server-only, and
 * importing it from the viewer dragged the internal API token into the client.
 */
export function documentUrl(code: string, documentId: string): string {
  return `/api/proxy/projects/${code}/documents/${documentId}/file`;
}

export class ProxyError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ProxyError";
  }
}

/**
 * Turn a failed response into a ProxyError carrying the API's own wording.
 *
 * FastAPI answers with `detail`, which is a string for a raised HTTPException
 * and a list of `{msg}` objects for a validation failure; formatApiDetail
 * flattens both. A non-JSON body (a gateway page, an HTML error) falls back to
 * the status text rather than throwing a parse error over the real failure.
 */
async function toProxyError(response: Response): Promise<ProxyError> {
  let detail: unknown = response.statusText;
  try {
    const body = await response.json();
    detail = body?.detail ?? response.statusText;
  } catch {
    /* non-JSON error body */
  }
  return new ProxyError(formatApiDetail(detail, response.statusText), response.status);
}

/**
 * A signed-out browser must not be told "Unexpected token '<'".
 *
 * The proxy route answers 401 once the session has gone; every caller routes
 * through here, so the redirect happens in one place instead of each screen
 * inventing its own handling.
 */
export function handleExpiredSession(status: number): void {
  if (status !== 401 || typeof window === "undefined") return;
  const here = window.location.pathname + window.location.search;
  // Deliberately a full-document navigation rather than router.push: the server
  // session is gone, so the whole React tree and every SWR cache it holds are
  // stale. A soft navigation would keep them and re-fetch into the same 401.
  const target = new URL("/signin", window.location.origin);
  target.searchParams.set("from", here);
  window.location.assign(target.toString());
}

/** Authenticated fetch that applies the same 401 redirect as proxyFetcher. */
export async function proxyFetch(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, init);
  if (!response.ok) handleExpiredSession(response.status);
  return response;
}

/**
 * A read against the proxy. Used directly as an SWR fetcher.
 *
 * `signal` lets a search that has been superseded by the next keystroke be
 * cancelled, so a slow early response cannot land after a fast later one.
 */
export async function proxyFetcher<T = unknown>(
  url: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    const error = await toProxyError(response);
    handleExpiredSession(error.status);
    throw error;
  }
  return (await response.json()) as T;
}

/**
 * A write against the proxy.
 *
 * Every mutation in the app used to hand-roll this: fetch, check `ok`, re-parse
 * the body for `detail`, toast something slightly different from the screen
 * next door, and hand back an implicit `any`. One helper gives them all the
 * same error text, the same 401 handling, and a real return type.
 *
 * Throws ProxyError on failure - callers report it, they do not inspect status
 * codes themselves.
 */
export async function proxyMutate<T = unknown>(
  path: string,
  options: {
    method?: "POST" | "PATCH" | "PUT" | "DELETE";
    body?: unknown;
    form?: FormData;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const { method = "POST", body, form, signal } = options;

  const response = await fetch(path, {
    method,
    // FormData sets its own multipart boundary; naming a Content-Type here
    // would produce one FastAPI cannot parse.
    headers: form ? undefined : { "Content-Type": "application/json" },
    body: form ?? (body === undefined ? undefined : JSON.stringify(body)),
    signal,
  }).catch((error: unknown) => {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ProxyError("Could not reach the server. Check your connection.", 0);
  });

  if (!response.ok) {
    const error = await toProxyError(response);
    handleExpiredSession(error.status);
    throw error;
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** The message to show a user for anything thrown by the helpers above. */
export function errorMessage(error: unknown): string {
  if (error instanceof ProxyError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}
