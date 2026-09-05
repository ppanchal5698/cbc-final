import { describe, expect, it } from "vitest";

import {
  resolveServiceAudience,
  resolveServiceBase,
  SERVICE_URLS,
} from "./service-routing";

describe("resolveServiceBase", () => {
  it("routes platform paths", () => {
    expect(resolveServiceBase(["jobs"])).toBe(SERVICE_URLS.platform);
    expect(resolveServiceBase(["projects"])).toBe(SERVICE_URLS.platform);
    expect(resolveServiceBase(["projects", "CBC-1"])).toBe(SERVICE_URLS.platform);
  });

  it("routes intake / extraction / quoting / catalog", () => {
    expect(resolveServiceBase(["projects", "CBC-1", "documents"])).toBe(
      SERVICE_URLS.intake,
    );
    expect(resolveServiceBase(["projects", "CBC-1", "line-items"])).toBe(
      SERVICE_URLS.extraction,
    );
    expect(resolveServiceBase(["projects", "CBC-1", "quote"])).toBe(
      SERVICE_URLS.quoting,
    );
    expect(resolveServiceBase(["catalog", "products"])).toBe(SERVICE_URLS.catalog);
    expect(resolveServiceBase(["reference", "margins"])).toBe(SERVICE_URLS.pricing);
  });
});

describe("resolveServiceAudience", () => {
  it("names the domain even when all service URLs coincide", () => {
    expect(resolveServiceAudience(["jobs"])).toBe("platform");
    expect(resolveServiceAudience(["ops", "spend"])).toBe("platform");
    expect(resolveServiceAudience(["projects", "CBC-1", "documents"])).toBe("intake");
    expect(resolveServiceAudience(["projects", "CBC-1", "line-items"])).toBe(
      "extraction",
    );
    expect(resolveServiceAudience(["price-books"])).toBe("catalog");
  });
});
