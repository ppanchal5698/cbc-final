import { test, expect } from "@playwright/test";

export { test, expect };

export const credentials = {
  estimator: {
    email: process.env.E2E_ESTIMATOR_EMAIL ?? "estimator@cbc.com",
    password: process.env.E2E_ESTIMATOR_PASSWORD ?? "opshub",
  },
  admin: {
    email: process.env.E2E_ADMIN_EMAIL ?? "admin@cbc.com",
    password: process.env.E2E_ADMIN_PASSWORD ?? "opshub",
  },
};

export async function signIn(
  page: import("@playwright/test").Page,
  email: string,
  password: string,
) {
  await page.goto("/signin");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/dashboard/);
}

/**
 * Open the "Create bid request" dialog from the bid board.
 *
 * The board mounts NewBidDialog twice: once in the header, always, and once in
 * the empty state when there are no bids and no search. Both are legitimate
 * affordances and either opens the same dialog - but an unscoped role query
 * matches both and is a strict-mode violation.
 *
 * It only bites on an empty board, which is why it passed on every developer
 * machine with data in it and failed the first time CI ran against a freshly
 * bootstrapped database. `.first()` is the header's, in DOM order, and resolves
 * whether the board has one button or two.
 */
export async function openNewBid(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: /create bid request/i }).first().click();
  await page.getByRole("dialog", { name: /create bid request/i }).waitFor();
}
