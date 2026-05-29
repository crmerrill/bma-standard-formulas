import { expect, test } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

test.describe("Pro-tool workflow quality gates", () => {
  test("wrong-result guard: default diagnostics reflect loss/shortfall reality", async ({ page }) => {
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

    await expect(page.getByText("Base-Case Default Diagnostics")).toBeVisible();
    await expect(page.getByText("Trigger Default").first()).toBeVisible();
    await expect(page.getByText("Interest Default").first()).toBeVisible();
    await expect(page.getByText("Principal Default").first()).toBeVisible();

    // Fixture includes recurring shortfall/writedown values for both bonds.
    // If these diagnostics regress, structurers would be misled on defaults.
    await expect(page.getByText("2 bond(s) with shortfall")).toBeVisible();
    await expect(page.getByText("2 bond(s) with loss/ending balance")).toBeVisible();
  });

  test("keyboard gate: history filtering and solver action are keyboard actionable", async ({ page }) => {
    await mountApiMocks(page);
    await setSessionState(page, { page: "history" });
    await page.goto("/");

    const structuredFilter = page.getByRole("button", { name: "Structured Deal", exact: true });
    await structuredFilter.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("1 run")).toBeVisible();

    const openSolverStudio = page.getByRole("button", { name: "Open Solver Studio" });
    await openSolverStudio.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Structuring Studio" })).toBeVisible();
  });
});
