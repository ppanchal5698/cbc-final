/**
 * Seed accounts from scripts/seed_db.py - local development only.
 *
 * SERVER ONLY. This module holds plaintext seed passwords, and it used to be
 * imported directly by the sign-in form, which put them in the client bundle of
 * every deployment - production included, where the quick-login buttons are not
 * even rendered. The page now reads the accounts on the server and passes only
 * what it decides to show.
 */
import "server-only";

export interface DevAccount {
  label: string;
  name: string;
  email: string;
  password: string;
}

const DEV_ACCOUNTS: DevAccount[] = [
  {
    label: "Estimator",
    name: "Estimator",
    email: "estimator@cbc.com",
    password: "opshub",
  },
  {
    label: "Admin",
    name: "Admin",
    email: "admin@cbc.com",
    password: "opshub",
  },
];

export function isDevQuickLoginEnabled(
  appEnv = process.env.APP_ENV,
  nodeEnv = process.env.NODE_ENV,
): boolean {
  const declared = appEnv?.trim().toLowerCase();
  if (declared) {
    return !["production", "prod", "staging"].includes(declared);
  }
  // Unset must not mean "development". `(appEnv ?? "development")` failed open:
  // a typoed or dropped APP_ENV enabled the quick-login buttons, and
  // internal-api.ts defaults the same way, so one missing variable also skipped
  // the committed-secrets check. Fail closed everywhere except an explicit
  // `next dev` session, where NODE_ENV is development and no build is emitted.
  return nodeEnv === "development";
}

/** The accounts to offer, or none at all outside local development. */
export function devAccounts(): DevAccount[] {
  return isDevQuickLoginEnabled() ? DEV_ACCOUNTS : [];
}
