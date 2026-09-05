import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Theme toggle", () => {
  test.beforeEach(async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
  });

  test("switches light and dark themes", async ({ page }) => {
    await page.goto("/dashboard");
    const root = page.locator("html");
    const toggle = page.getByRole("banner").getByRole("button", { name: /toggle theme/i });

    const initial = await root.getAttribute("data-theme");
    await toggle.click();
    await expect(root).not.toHaveAttribute("data-theme", initial ?? "dark");
    await toggle.click();
    await expect(root).toHaveAttribute("data-theme", initial ?? "dark");
  });
});
