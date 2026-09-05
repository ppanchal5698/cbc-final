import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Not found", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("unknown route shows branded in-app 404", async ({ page }) => {
    await page.goto("/nonexistent-route-test");

    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Back to the dashboard" })).toBeVisible();
    await expect(page.getByRole("navigation")).toBeVisible();
    await expect(page.getByText("This page could not be found")).not.toBeVisible();
  });
});
