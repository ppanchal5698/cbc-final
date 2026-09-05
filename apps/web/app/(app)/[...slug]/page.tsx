import { notFound } from "next/navigation";

/** Catch unmatched app routes so they render (app)/not-found inside the shell. */
export default function UnmatchedAppRoute() {
  notFound();
}
