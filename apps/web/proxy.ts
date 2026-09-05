/**
 * Route protection.
 *
 * Next 16 renamed `middleware` to `proxy` and pins it to the Node runtime -
 * see node_modules/next/dist/docs/01-app/02-guides/upgrading/version-16.md
 */
import { auth } from "@/auth";

export default auth((request) => {
  const signedIn = !!request.auth;
  const { pathname } = request.nextUrl;

  if (!signedIn && pathname !== "/signin") {
    return Response.redirect(new URL("/signin", request.nextUrl));
  }
  if (signedIn && pathname === "/signin") {
    return Response.redirect(new URL("/dashboard", request.nextUrl));
  }
});

export const config = {
  // `api/proxy` is excluded deliberately. It runs its own auth() check and
  // answers 401, which the browser can act on; redirecting it instead handed
  // every SWR call a 200 carrying the sign-in HTML, so each screen failed with
  // "Unexpected token '<'" the moment a session expired.
  matcher: [
    "/((?!api/auth|api/proxy|_next/static|_next/image|favicon\.ico|pdf\.worker\.min\.mjs|.*\.svg).*)",
  ],
};
