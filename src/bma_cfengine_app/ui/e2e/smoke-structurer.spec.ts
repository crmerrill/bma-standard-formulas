import { expect, test } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

test.describe("Structurer UX smoke", () => {
  test("run history supports type filtering and solver entry points", async ({ page }) => {
    await mountApiMocks(page);
    await setSessionState(page, { page: "history" });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Run History" })).toBeVisible();
    await expect(page.getByText("2 runs")).toBeVisible();

    await page.getByRole("button", { name: "Structured Deal", exact: true }).click();
    await expect(page.getByText("1 run")).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Analysis" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Solver Studio" })).toBeVisible();
  });

  test("structured analysis renders large cashflow preview deterministically", async ({ page }) => {
    await mountApiMocks(page);
    await setSessionState(page, {
      page: "structured_analysis",
      structuredRunId: "run_struct_001",
      collateralRiskSettings: {
        productFamily: "PRIME_JUMBO",
        mode: "none",
      },
    });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Structured Deal Analysis" })).toBeVisible();
    await expect(page.getByText("Run Selection")).toBeVisible();
    await expect(page.getByText("Portfolio Cashflow Visuals")).toBeVisible();
    await expect(page.getByText("Base-Case Default Diagnostics")).toBeVisible();
  });
});
