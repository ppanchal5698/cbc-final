/**
 * Reject path segments that would escape the /api/ prefix once URL-normalised.
 * The catch-all route receives decoded segments, so %2F..%2F and bare .. both
 * need blocking before `new URL(API_BASE + "/api/" + joined)`.
 */

const ENCODED_SEPARATOR = /%2f|%5c/i;

export function rejectUnsafeProxySegments(path: string[]): string | null {
  for (const segment of path) {
    if (segment === "..") {
      return "path traversal is not allowed";
    }
    if (ENCODED_SEPARATOR.test(segment)) {
      return "encoded path separators are not allowed";
    }
  }
  return null;
}

export function buildProxyTarget(apiBase: string, path: string[]): URL {
  const target = new URL(`${apiBase}/api/${path.join("/")}`);
  if (!target.pathname.startsWith("/api/") && target.pathname !== "/api") {
    throw new Error("proxy path escaped the /api prefix");
  }
  return target;
}
