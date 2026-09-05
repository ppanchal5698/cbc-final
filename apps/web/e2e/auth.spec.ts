import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Authentication", () => {
  test("redirects unauthenticated users to sign-in", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/signin/);
  });

  test("rejects invalid credentials", async ({ page }) => {
    await page.goto("/signin");
    await page.getByLabel("Email").fill("nobody@example.com");
    await page.getByLabel("Password").fill("wrong-password");
    await page.getByRole("button", { name: "Sign in" }).click();

    // Not getByRole("alert"): Next.js renders its own route announcer with that
    // role on every page, so the query matched two elements and resolved to the
    // empty one. The form gives its error a stable id.
    await expect(page.locator("#signin-error")).toContainText(/do not match/i);
  });

  test("does not say whether the address exists", async ({ page }) => {
    // The same wording either way - the timing is equalised server-side too.
    await page.goto("/signin");
    await page.getByLabel("Email").fill(credentials.estimator.email);
    await page.getByLabel("Password").fill("definitely-not-the-password");
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.locator("#signin-error")).toContainText(/do not match/i);
  });

  test("signs in and reaches dashboard", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);

    // The dashboard h1 is a greeting - "Good morning, Kevin" - not the words
    // "dashboard" or "estimator home". Assert the landing, not a copy string
    // that changes with the time of day and the signed-in name.
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 15_000 });
  });
});
