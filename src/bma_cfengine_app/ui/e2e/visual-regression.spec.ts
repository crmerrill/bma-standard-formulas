import { expect, test } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

test.describe("Visual regression", () => {
  test("run history shell remains visually stable", async ({ page }) => {
    await mountApiMocks(page);
    await setSessionState(page, { page: "history" });
    await page.goto("/");
    await expect(page).toHaveScreenshot("run-history.png", {
      fullPage: true,
      animations: "disabled",
    });
  });

  test("structured analysis remains visually stable", async ({ page }) => {
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
    await expect(page).toHaveScreenshot("structured-analysis.png", {
      fullPage: true,
      animations: "disabled",
    });
  });
});
