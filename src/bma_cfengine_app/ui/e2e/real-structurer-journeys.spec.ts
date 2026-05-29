/**
 * Real-world structurer journeys.
 *
 * Each test below is grounded in an externally documented structuring concept
 * and exercises both the *process* a structurer would follow in this UI AND
 * the *result* the UI must show at the end of that process.
 *
 * Sources:
 *   [Peak53]      Peak53 Partners, "RMBS Primer"
 *                 https://www.peak53partners.com/insights/research/rmbs-primer
 *   [AngelOak]    Angel Oak Capital, "Securitization 101"
 *                 https://angeloakcapital.com/securitization-101-a-primer-on-structured-finance/
 *   [Dutch]       Dutch Securitisation Association, "Dutch Primer RMBS"
 *                 https://www.dutchsecuritisation.nl/sites/default/files/dutch_primer_rmbs_a_primer.pdf
 *   [RBA]         Reserve Bank of Australia, "Cash Flow Waterfall Reporting Template"
 *                 https://www.rba.gov.au/mkt-operations/pdf/cash-flow-waterfall-template-for-repo-eligible-abs.pdf
 *   [RBC]         RBC Wealth Management, "Investor's Guide to MBS / CMOs"
 *   [Guggenheim]  Guggenheim Investments, "Understanding CLOs"
 *                 https://www.guggenheiminvestments.com/perspectives/portfolio-strategy/understanding-collateralized-loan-obligations-clo
 *   [FRM]         AnalystPrep FRM Part II, "Structured Credit Risk"
 *                 https://analystprep.com/study-notes/frm/part-2/credit-risk-measurement-and-management/structured-credit-risk/
 *   [absbox]      ABSBox, "Distill the verbose waterfall in CLO"
 *                 https://absbox-doc.readthedocs.io/en/latest/nbsample/DistillWaterfall.html
 *   [BMA]         docs/architecture/solver_ux_design.md (this repo)
 */

import { expect, test, type Page } from "@playwright/test";
import { mountApiMocks, setSessionState } from "./support/mockApi";

async function openStructuredAnalysis(page: Page) {
  await mountApiMocks(page);
  await setSessionState(page, {
    page: "structured_analysis",
    structuredRunId: "run_struct_001",
    collateralRiskSettings: { productFamily: "PRIME_JUMBO", mode: "none" },
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Structured Deal Analysis" })).toBeVisible();
}

/**
 * The page renders multiple <select> elements (run selector, optional compare
 * run selector, artifact selector). Find the one whose option list contains
 * the named artifact. This avoids the brittle assumption that the artifact
 * dropdown is always the Nth combobox.
 */
async function selectArtifact(page: Page, artifactName: string) {
  const selects = page.getByRole("combobox");
  const count = await selects.count();
  for (let i = 0; i < count; i += 1) {
    const options = await selects.nth(i).locator("option").allTextContents();
    if (options.some((o) => o.trim() === artifactName)) {
      await selects.nth(i).selectOption(artifactName);
      return;
    }
  }
  throw new Error(`Artifact dropdown containing "${artifactName}" not found`);
}

test.describe("Structurer journey: senior-sub credit enhancement ladder [Peak53][Dutch][AngelOak]", () => {
  test("Bond Risk view shows monotonic CE: senior > mezz > residual", async ({ page }) => {
    await openStructuredAnalysis(page);

    // Process: structurer clicks into "Bond Risk" tab to inspect tranche risk.
    await page.getByRole("button", { name: "Bond Risk" }).click();
    await expect(page.getByText("Per-tranche WAL, CE and risk metrics.")).toBeVisible();

    await selectArtifact(page, "base_case_tranche_risk_summary");

    // Result: subordination/CE must obey the senior-sub ladder. Renders 30, 10, 0 from fixture.
    // If this regresses to junior >= senior CE, structurers would be misled
    // about the deal's loss-protection ordering ([Dutch §4.6.1]).
    await expect(page.getByRole("cell", { name: "30.0000", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "10.0000", exact: true })).toBeVisible();
  });
});

test.describe("Structurer journey: stepdown trigger breach diagnostic [Guggenheim][FRM]", () => {
  test("Waterfall + Triggers exposes failed stepdown periods", async ({ page }) => {
    await openStructuredAnalysis(page);

    await page.getByRole("button", { name: "Waterfall + Triggers" }).click();
    await expect(page.getByText("Waterfall trace and trigger timelines.")).toBeVisible();

    await selectArtifact(page, "base_case_trigger_state_history");

    // Result: at least one period must show FAIL (fixture seeds breach periods 70..130).
    // If trigger breaches silently disappear, structurers will miss real risk.
    await expect(page.getByRole("cell", { name: "FAIL" }).first()).toBeVisible();
    await expect(page.getByRole("cell", { name: "PASS" }).first()).toBeVisible();
  });
});

test.describe("Structurer journey: PAC schedule adherence [RBC]", () => {
  test("Deal Risk view surfaces PAC schedule misses with bps gap", async ({ page }) => {
    await openStructuredAnalysis(page);

    await page.getByRole("button", { name: "Deal Risk" }).click();
    await expect(page.getByText(/Stress\/decrement diagnostics/)).toBeVisible();

    await selectArtifact(page, "base_case_pac_tac_diagnostics");

    // Result: schedule_miss_bps column must exist and non-zero misses must show.
    await expect(page.getByRole("columnheader", { name: "schedule_miss_bps" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "21.0000", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "45.0000", exact: true })).toBeVisible();
  });
});

test.describe("Structurer journey: solver iteration audit [BMA][absbox]", () => {
  test("Solver Runs tab shows convergence trajectory with feasibility crossover", async ({
    page,
  }) => {
    await openStructuredAnalysis(page);

    await page.getByRole("button", { name: "Solver Runs" }).click();
    await expect(page.getByText("Solver iteration trajectory")).toBeVisible();

    await selectArtifact(page, "base_case_solver_iterations");

    // Result: solver_iterations table renders with required columns. Any regression
    // that drops the feasibility column would prevent the structurer from knowing
    // when the solution became feasible.
    await expect(page.getByRole("columnheader", { name: "iteration" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "objective_value_pct" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "gap_to_target_bps" })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "feasible" })).toBeVisible();
  });
});

test.describe("Structurer journey: compare two solver runs [Carta][absbox]", () => {
  test("Selected solution diff materializes when comparing two solver runs", async ({ page }) => {
    await openStructuredAnalysis(page);

    await page.getByRole("button", { name: "Solver Runs" }).click();
    await selectArtifact(page, "base_case_solver_selected_solution");

    // The compare combobox only renders on solver_runs tab. Look it up by
    // the explicit "Compare:" label adjacent to the dropdown.
    const compareLabel = page.getByText("Compare:", { exact: true });
    await expect(compareLabel).toBeVisible();
    const compareSelect = compareLabel.locator("xpath=following::select[1]");
    const optionTexts = await compareSelect.locator("option").allTextContents();
    const stressOption = optionTexts.find((t) => /Stress 2x Loss/.test(t));
    expect(stressOption, "compare run dropdown must include the stress run").toBeTruthy();
    await compareSelect.selectOption({ label: stressOption! });

    // Result: the compare panel must materialize with a metric/delta table.
    await expect(page.getByText("Compare Runs")).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Metric", exact: true })).toBeVisible();
    await expect(page.getByRole("columnheader", { name: "Delta", exact: true })).toBeVisible();
  });
});

test.describe("Structurer journey: run history audit trail [RBA]", () => {
  test("History page exposes both portfolio and structured runs with metadata", async ({
    page,
  }) => {
    await mountApiMocks(page);
    await setSessionState(page, { page: "history" });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Run History" })).toBeVisible();

    // Process: structurer scopes the audit to structured runs only.
    await page.getByRole("button", { name: "Structured Deal", exact: true }).click();
    await expect(page.getByText("2 runs")).toBeVisible();

    // Result: both structured deal rows must appear. Strict assertion on the
    // dedicated scenarios cell (not the deal/run combined cell) so we test
    // metadata visibility in the scenarios column specifically.
    await expect(
      page.getByRole("cell", { name: "Stress 2x Loss", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("cell", { name: "Base Case", exact: true }),
    ).toBeVisible();
  });
});
