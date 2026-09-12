import { describe, expect, it } from "vitest";

import {
  resolveServiceAudience,
  resolveServiceBase,
  SERVICE_URLS,
} from "./service-routing";

describe("resolveServiceBase", () => {
  it("routes every path to the monolith", () => {
    expect(resolveServiceBase(["jobs"])).toBe(SERVICE_URLS.platform);
    expect(resolveServiceBase(["projects"])).toBe(SERVICE_URLS.platform);
    expect(resolveServiceBase(["projects", "CBC-1"])).toBe(SERVICE_URLS.platform);
    expect(resolveServiceBase(["projects", "CBC-1", "documents"])).toBe(
      SERVICE_URLS.platform,
    );
    expect(resolveServiceBase(["projects", "CBC-1", "line-items"])).toBe(
      SERVICE_URLS.platform,
    );
    expect(resolveServiceBase(["reference", "margins"])).toBe(
      SERVICE_URLS.platform,
    );
    expect(resolveServiceBase(["projects", "CBC-1", "quote"])).toBe(
      SERVICE_URLS.platform,
    );
    expect(resolveServiceBase(["catalog", "products"])).toBe(
      SERVICE_URLS.platform,
    );
    expect(resolveServiceBase(["price-books"])).toBe(SERVICE_URLS.platform);
  });
});

describe("resolveServiceAudience", () => {
  it("always claims platform", () => {
    expect(resolveServiceAudience(["jobs"])).toBe("platform");
    expect(resolveServiceAudience(["ops", "spend"])).toBe("platform");
    expect(resolveServiceAudience(["projects", "CBC-1", "documents"])).toBe(
      "platform",
    );
    expect(resolveServiceAudience(["projects", "CBC-1", "line-items"])).toBe(
      "platform",
    );
    expect(resolveServiceAudience(["reference", "margins"])).toBe("platform");
    expect(resolveServiceAudience(["projects", "CBC-1", "quote"])).toBe(
      "platform",
    );
    expect(resolveServiceAudience(["catalog", "products"])).toBe("platform");
    expect(resolveServiceAudience(["price-books"])).toBe("platform");
  });
});
