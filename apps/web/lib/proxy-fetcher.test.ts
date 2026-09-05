import { describe, expect, it, vi, beforeEach } from "vitest";

import {
  ProxyError,
  errorMessage,
  handleExpiredSession,
  proxyFetcher,
  proxyMutate,
} from "@/lib/proxy-fetcher";

describe("proxy-fetcher", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  it("parses JSON error detail into ProxyError", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Bid not found" }), { status: 404 }),
    );

    await expect(proxyFetcher("/api/proxy/projects/missing")).rejects.toMatchObject({
      message: "Bid not found",
      status: 404,
    });
  });

  it("redirects to sign-in on 401", () => {
    const assign = vi.fn();
    vi.stubGlobal("window", {
      location: {
        pathname: "/bids",
        search: "?stage=intake",
        origin: "http://localhost:3000",
        assign,
      },
    });

    handleExpiredSession(401);

    expect(assign).toHaveBeenCalledWith(
      "http://localhost:3000/signin?from=%2Fbids%3Fstage%3Dintake",
    );
  });

  it("returns parsed JSON from proxyMutate", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ ok: true }), { status: 200 }),
    );

    const result = await proxyMutate<{ ok: boolean }>("/api/proxy/test");
    expect(result).toEqual({ ok: true });
  });

  it("maps network failures to ProxyError", async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(proxyMutate("/api/proxy/test")).rejects.toBeInstanceOf(ProxyError);
  });

  it("formats ProxyError via errorMessage", () => {
    expect(errorMessage(new ProxyError("Denied", 403))).toBe("Denied");
  });
});
