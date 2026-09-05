import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Review queue", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("opens a panel instead of navigating away", async ({ page }) => {
    await page.goto("/dashboard");
    await page.getByRole("button", { name: /review queue/i }).click();
    await expect(page.getByText("Lines flagged for your review")).toBeVisible();
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});
