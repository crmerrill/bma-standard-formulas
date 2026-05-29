import { expect, test } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

test.describe("Performance budgets", () => {
  test("tab transition remains under budget on large run payload", async ({ page }) => {
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

    const start = Date.now();
    await page.getByRole("button", { name: "Waterfall + Triggers" }).click();
    await page.getByRole("button", { name: "Bond Cashflows" }).click();
    await expect(page.getByText("Data Preview")).toBeVisible();
    const elapsedMs = Date.now() - start;

    // Quality ratchet for structurer productivity: do not loosen this
    // threshold to make CI pass. Fix the underlying UI performance instead.
    expect(elapsedMs).toBeLessThan(2500);
  });
});
