import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Admin settings", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.admin.email, credentials.admin.password);
  });

  test("lands on the AI section and has a Pipeline tab", async ({ page }) => {
    await page.goto("/settings");
    await expect(page).toHaveURL(/\/settings\/ai$/);
    await expect(page.getByRole("heading", { name: "Bid-set reader" })).toBeVisible({ timeout: 15_000 });
    const tabs = page.getByRole("navigation", { name: "Settings sections" });
    await tabs.getByRole("link", { name: /Pipeline/ }).click();
    await expect(page).toHaveURL(/\/settings\/pipeline$/);
  });

  test("pricing, reference data, users and audit are pages of their own in the rail", async ({ page }) => {
    await page.goto("/dashboard");
    const rail = page.getByRole("navigation", { name: "Main Navigation" });
    for (const [label, path, heading] of [
      ["Pricing", "/pricing", "Margin framework"],
      ["Reference data", "/reference-data", "Finish crosswalk"],
      ["Users", "/users", "Users"],
      ["Audit log", "/audit", "Audit log"],
    ] as const) {
      await rail.getByRole("link", { name: label, exact: true }).click();
      await expect(page).toHaveURL(new RegExp(`${path}$`));
      await expect(page.getByRole("heading", { name: heading, exact: true }).first()).toBeVisible({ timeout: 15_000 });
    }
  });

  test("the old settings addresses still land", async ({ page }) => {
    for (const [from, to] of [
      ["/settings/pricing", "/pricing"],
      ["/settings/reference", "/reference-data"],
      ["/settings/users", "/users"],
    ] as const) {
      await page.goto(from);
      await expect(page).toHaveURL(new RegExp(`${to}$`));
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
    await page.goto("/settings/pipeline");
    await expect(page).toHaveURL(/\/settings$/);
  });

  test("admin pages are hidden from and refused to a non-admin", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
    await page.goto("/dashboard");
    const rail = page.getByRole("navigation", { name: "Main Navigation" });
    await expect(rail.getByRole("link", { name: "Pricing", exact: true })).toHaveCount(0);
    for (const path of ["/pricing", "/reference-data", "/users", "/audit"]) {
      await page.goto(path);
      await expect(page).toHaveURL(/\/dashboard$/);
    }
  });
});
