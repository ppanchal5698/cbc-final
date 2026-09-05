/**
 * Pass-through to the owning domain FastAPI service.
 *
 * The browser needs a same-origin path for PDFs and page renders (the viewer
 * fetches them directly), and this keeps each service address a server-side
 * detail. Path segments select platform / intake / extraction / pricing /
 * quoting / catalog via `resolveServiceBase`.
 */
import { NextRequest } from "next/server";

import { auth } from "@/auth";
import { internalApiHeaders } from "@/lib/internal-api";
import { buildProxyTarget, rejectUnsafeProxySegments } from "@/lib/proxy-path";
import { resolveServiceAudience, resolveServiceBase } from "@/lib/service-routing";

const UPSTREAM_REQUEST_HEADERS = [
  "accept",
  "accept-language",
  "content-type",
  "if-none-match",
  "range",
] as const;

const UPSTREAM_RESPONSE_HEADERS = [
  "content-type",
  "cache-control",
  "etag",
  "content-disposition",
] as const;

async function proxy(request: NextRequest, path: string[]) {
  const session = await auth();
  if (!session) return new Response("Unauthorized", { status: 401 });

  const unsafe = rejectUnsafeProxySegments(path);
  if (unsafe) {
    return Response.json({ detail: unsafe }, { status: 400 });
  }

  const apiBase = resolveServiceBase(path);
  const audience = resolveServiceAudience(path);

  let target: URL;
  try {
    target = buildProxyTarget(apiBase, path);
  } catch {
    return Response.json({ detail: "invalid proxy path" }, { status: 400 });
  }

  request.nextUrl.searchParams.forEach((value, key) => {
    if (key !== "actor") {
      target.searchParams.set(key, value);
    }
  });

  const traceId =
    request.headers.get("x-trace-id")?.trim() || crypto.randomUUID();

  const headers = new Headers();
  for (const name of UPSTREAM_REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) {
      headers.set(name, value);
    }
  }
  for (const [key, value] of Object.entries(
    await internalApiHeaders(session.user?.email, audience, traceId),
  )) {
    headers.set(key, value);
  }

  const contentType = request.headers.get("content-type") ?? "";

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
    signal: request.signal,
  };

  if (!["GET", "HEAD"].includes(request.method)) {
    if (contentType.includes("multipart/form-data")) {
      const form = await request.formData();
      const upstreamForm = new FormData();
      for (const [key, value] of form.entries()) {
        upstreamForm.append(key, value);
      }
      init.body = upstreamForm;
      headers.delete("content-type");
    } else {
      init.body = await request.arrayBuffer();
    }
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return new Response(null, { status: 499 });
    }
    return Response.json(
      { detail: `Cannot reach the API at ${apiBase}.` },
      { status: 503 },
    );
  }

  const responseHeaders = new Headers();
  for (const name of UPSTREAM_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) {
      responseHeaders.set(name, value);
    }
  }
  const upstreamTrace = upstream.headers.get("x-trace-id") ?? traceId;
  if (upstreamTrace) {
    responseHeaders.set("X-Trace-Id", upstreamTrace);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
export async function POST(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
export async function PUT(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
export async function PATCH(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
export async function DELETE(request: NextRequest, ctx: Ctx) {
  return proxy(request, (await ctx.params).path);
}
