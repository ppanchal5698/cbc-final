/**
 * Only follow same-origin relative paths after sign-in.
 * Prefix checks miss backslash tricks: "/\\/evil.com" passes startsWith("/")
 * but WHATWG URL parsing normalises \ to / and resolves off-host.
 */
export function safeRedirectPath(from: string | null | undefined): string {
  if (!from || !from.startsWith("/")) {
    return "/dashboard";
  }
  try {
    const resolved = new URL(from, "http://local.invalid");
    if (resolved.origin !== "http://local.invalid") {
      return "/dashboard";
    }
    return resolved.pathname + resolved.search + resolved.hash;
  } catch {
    return "/dashboard";
  }
}
