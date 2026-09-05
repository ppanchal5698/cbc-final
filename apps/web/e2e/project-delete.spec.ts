import { test, expect } from "@playwright/test";

import { credentials, openNewBid, signIn } from "./helpers";

test.describe("Project delete", () => {
  test("admin can delete a bid from intake", async ({ page }) => {
    await signIn(page, credentials.admin.email, credentials.admin.password);

    const jobName = `E2E delete ${Date.now()}`;
    await page.goto("/bids");
    await openNewBid(page);
    await page.getByLabel(/job name|name/i).fill(jobName);
    await page.getByRole("button", { name: /create/i }).click();
    await page.waitForURL(/\/bids\/([^/]+)\/intake/);

    const match = page.url().match(/\/bids\/([^/]+)\/intake/);
    const code = match?.[1];
    expect(code).toBeTruthy();

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: /delete bid/i }).click();

    await expect(page.getByRole("dialog", { name: /confirm delete/i })).toBeVisible();
    await page.getByLabel(new RegExp(`Type ${code} to confirm delete`, "i")).fill(code!);
    await page.getByRole("button", { name: /delete permanently/i }).click();

    await page.waitForURL(/\/bids$/);
    await expect(page.getByRole("heading", { name: "Bid board" })).toBeVisible();

    await page.getByRole("searchbox", { name: /search bids/i }).fill(jobName);
    await page.waitForURL(/q=/);
    await expect(page.getByText(jobName)).toHaveCount(0);
  });
});
