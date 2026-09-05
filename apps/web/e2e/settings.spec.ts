import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Admin settings", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.admin.email, credentials.admin.password);
  });

  test("shows pipeline settings for admin", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByRole("heading", { name: "Pipeline defaults" })).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByRole("heading", { name: "Price book freshness" })).toBeVisible();
    await expect(page.getByText(/autopilot default/i)).toBeVisible();
  });
});

test.describe("Estimator settings access", () => {
  test("shows limited message for non-admin", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
    await page.goto("/settings");
    await expect(page.getByText(/limited to admin/i)).toBeVisible({ timeout: 15_000 });
  });
});
