import { expect, test } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

async function goStructuredAnalysis(page: any) {
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
}

test.describe("Pro-tool layout integrity", () => {
  test("layout scales across professional desktop viewport sizes", async ({ page }) => {
    const viewports = [
      { width: 1280, height: 800 },
      { width: 1440, height: 900 },
      { width: 1920, height: 1080 },
    ];

    for (const viewport of viewports) {
      await page.setViewportSize(viewport);
      await goStructuredAnalysis(page);
      await expect(page.getByText("Run Selection")).toBeVisible();
      await expect(page.getByText("Data Preview")).toBeVisible();

      const overflow = await page.evaluate(() => ({
        docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
      }));

      // Horizontal clipping/overflow is unacceptable in a pro desktop workflow.
      expect(Math.max(overflow.docOverflow, overflow.bodyOverflow)).toBeLessThanOrEqual(2);
    }
  });

  test("collapsible panels toggle cleanly without stale visual traces", async ({ page }) => {
    await goStructuredAnalysis(page);

    const artifactsHeader = page.getByRole("button", { name: "Artifacts" });
    await expect(artifactsHeader).toBeVisible();
    await expect(page.getByText("Artifact:")).toHaveCount(1);

    for (let i = 0; i < 3; i += 1) {
      await artifactsHeader.click(); // close
      await expect(page.getByText("Artifact:")).toHaveCount(0);
      await artifactsHeader.click(); // open
      await expect(page.getByText("Artifact:")).toHaveCount(1);
    }

    // Ensure panel landmarks are still singular and no duplicate ghost panel copies exist.
    await expect(page.getByRole("button", { name: "Artifacts" })).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Data Preview" })).toHaveCount(1);
  });
});
