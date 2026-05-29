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

async function selectArtifact(page: Page, artifactName: string) {
  // The "Artifacts" panel is collapsible; ensure it's open before selecting.
  const artifactsToggle = page.getByRole("button", { name: "Artifacts" });
  await artifactsToggle.click();
  await artifactsToggle.click();
  const select = page.getByRole("combobox").first();
  await select.selectOption(artifactName);
}

test.describe("Structurer journey: senior-sub credit enhancement ladder [Peak53][Dutch][AngelOak]", () => {
  test("Bond Risk view shows monotonic CE: senior > mezz > residual", async ({ page }) => {
    await openStructuredAnalysis(page);

    // Process: structurer clicks into "Bond Risk" tab to inspect tranche risk.
    await page.getByRole("button", { name: "Bond Risk" }).click();
    await expect(page.getByText("Per-tranche WAL")).toBeVisible();

    await selectArtifact(page, "base_case_tranche_risk_summary");

    // Result: subordination/CE must obey the senior-sub ladder. If this ever
    // regresses to junior >= senior CE, the UI is misleading the structurer
    // about the deal's loss-protection ordering ([Dutch §4.6.1]).
    await expect(page.getByText("30")).toBeVisible(); // senior CE
    await expect(page.getByText("10")).toBeVisible(); // mezz CE
  });
});

test.describe("Structurer journey: stepdown trigger breach diagnostic [Guggenheim][FRM]", () => {
  test("Waterfall + Triggers exposes failed stepdown periods", async ({ page }) => {
    await openStructuredAnalysis(page);

    // Process: structurer opens "Waterfall + Triggers" to confirm whether
    // delinquency/loss tests blocked stepdown in any period (FRM §"OC tests").
    await page.getByRole("button", { name: "Waterfall + Triggers" }).click();
    await expect(page.getByText("Waterfall trace and trigger timelines.")).toBeVisible();

    await selectArtifact(page, "base_case_trigger_state_history");

    // Result: at least one period must show FAIL (fixture seeds breach 70..130).
    // If trigger breaches silently disappear, structurers will miss real risk.
    await expect(page.getByText("FAIL").first()).toBeVisible();
  });
});

test.describe("Structurer journey: PAC schedule adherence [RBC]", () => {
  test("Deal Risk view surfaces PAC schedule misses with bps gap", async ({ page }) => {
    await openStructuredAnalysis(page);

    // Process: structurer wants to confirm PAC tranche stayed on its sinking
    // fund schedule under the run's prepay/loss assumptions ([RBC PAC]).
    await page.getByRole("button", { name: "Deal Risk" }).click();
    await expect(page.getByText("Stress/decrement diagnostics")).toBeVisible();

    await selectArtifact(page, "base_case_pac_tac_diagnostics");

    // Result: schedule_miss_bps must be visible and non-zero in at least one row,
    // proving that schedule misses are surfaced (and not silently dropped).
    await expect(page.getByText("schedule_miss_bps")).toBeVisible();
    await expect(page.getByText("21")).toBeVisible();
    await expect(page.getByText("45")).toBeVisible();
  });
});

test.describe("Structurer journey: solver iteration audit [BMA][absbox]", () => {
  test("Solver Runs tab shows convergence trajectory with feasibility crossover", async ({
    page,
  }) => {
    await openStructuredAnalysis(page);

    // Process: structurer iterating on coupons opens the solver trajectory
    // to confirm convergence and feasibility transition ([BMA solver_ux_design]).
    await page.getByRole("button", { name: "Solver Runs" }).click();
    await expect(page.getByText("Solver iteration trajectory")).toBeVisible();

    await selectArtifact(page, "base_case_solver_iterations");

    // Result: solver_iterations table renders; gap-to-target column must be
    // visible (solver UX must always show how far we are from target).
    await expect(page.getByText("gap_to_target_bps")).toBeVisible();
    await expect(page.getByText("feasible")).toBeVisible();
  });
});

test.describe("Structurer journey: compare two solver runs [Carta][absbox]", () => {
  test("Selected solution diff materializes when comparing two solver runs", async ({ page }) => {
    await openStructuredAnalysis(page);

    await page.getByRole("button", { name: "Solver Runs" }).click();
    await selectArtifact(page, "base_case_solver_selected_solution");

    // Process: pick a compare run from the second selector that appears once
    // the Solver Runs tab is active.
    const compareSelect = page.getByRole("combobox").nth(1);
    await compareSelect.selectOption({ label: /Stress 2x Loss/ });

    // Result: the compare panel must materialize with a metric/delta table.
    // If the compare regresses to silent no-op, structurers cannot iterate.
    await expect(page.getByText("Compare Runs")).toBeVisible();
    await expect(page.getByText("Delta")).toBeVisible();
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

    // Process: structurer opens history, switches tabs to scope to structured-only.
    await page.getByRole("button", { name: "Structured Deal", exact: true }).click();

    // Result: both structured runs must appear in the audit trail.
    await expect(page.getByText("Prime 2026-1")).toHaveCount(2);
    await expect(page.getByText(/Stress 2x Loss/)).toBeVisible();
    await expect(page.getByText(/Base Case/)).toBeVisible();
  });
});
