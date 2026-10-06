import { test, expect } from "@playwright/test";

import { credentials, signIn } from "./helpers";

test.describe("Memory graph", () => {
  test("an admin sees what the graph holds and can queue a sync", async ({ page }) => {
    await signIn(page, credentials.admin.email, credentials.admin.password);
    await page.goto("/dashboard");
    const rail = page.getByRole("navigation", { name: "Main Navigation" });
    await rail.getByRole("link", { name: "Memory graph", exact: true }).click();
    await expect(page).toHaveURL(/\/memory$/);
    await expect(page.getByRole("heading", { name: "What the memory holds" })).toBeVisible({ timeout: 15_000 });

    // Neo4j is part of the stack, so the graph answers - empty or not.
    await expect(page.getByText("Successful bids")).toBeVisible({ timeout: 15_000 });
    const sync = page.getByRole("button", { name: "Sync now" });
    await expect(sync).toBeEnabled();
    await sync.click();
    await expect(page.getByText(/Sync queued/)).toBeVisible({ timeout: 15_000 });

    // The agents' work, beside the counts: what the steward found, what the historian wrote.
    await expect(page.getByRole("heading", { name: "Findings" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "What customers' bids show" })).toBeVisible();
  });

  test("an estimator does not see it and is refused it", async ({ page }) => {
    await signIn(page, credentials.estimator.email, credentials.estimator.password);
    await page.goto("/dashboard");
    const rail = page.getByRole("navigation", { name: "Main Navigation" });
    await expect(rail.getByRole("link", { name: "Memory graph", exact: true })).toHaveCount(0);
    await page.goto("/memory");
    await expect(page).toHaveURL(/\/dashboard$/);
  });
});
