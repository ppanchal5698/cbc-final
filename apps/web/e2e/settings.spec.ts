import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Admin settings", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.admin.email, credentials.admin.password);
  });

  test("lands on the AI section and reaches every other section by its tab", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings\/ai$/);
    await expect(page.getByRole("heading", { name: "Bid-set reader" })).toBeVisible({ timeout: 15_000 });
    const tabs = page.getByRole("navigation", { name: "Settings sections" });
    for (const [label, path, heading] of [
      ["Pricing", "/settings/pricing", "Margin framework"],
      ["Reference data", "/settings/reference", "Finish crosswalk"],
      ["Users & audit", "/settings/users", "Audit log"],
    ] as const) {
      await tabs.getByRole("link", { name: new RegExp(label) }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", { name: heading, exact: false }).first()).toBeVisible({ timeout: 15_000 });
    }
  });

  test("shows pipeline settings for admin", async ({ page }) => {
    await page.goto("/settings/pipeline");
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

  test("an admin section sends a non-admin back to the overview", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
    await page.goto("/settings/pricing");
    await expect(page).toHaveURL(/\/settings$/);
  });
});
