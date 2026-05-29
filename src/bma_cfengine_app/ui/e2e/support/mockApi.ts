import type { Page, Route } from "@playwright/test";
import {
  makeBondCashflowRows,
  makePacTacRows,
  makeSolverCeLadder,
  makeSolverIterations,
  makeSolverSelectedSolution,
  makeTrancheRiskRows,
  makeTriggerStateRows,
  makeWaterfallTraceRows,
  runListFixture,
  structuredArtifacts,
  structuredArtifactsFixture,
} from "./fixtures";

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

function previewPayload(section: string, columns: string[], rows: Array<Record<string, unknown>>) {
  return {
    section,
    columns,
    rows,
    row_count: rows.length,
    truncated: false,
  };
}

const PREVIEW_HANDLERS: Record<string, () => unknown> = {
  base_case_bond_cashflows: () =>
    previewPayload(
      "base_case_bond_cashflows",
      [
        "period",
        "tranche_id",
        "total_principal",
        "interest_paid",
        "writedown",
        "end_balance",
        "interest_shortfall",
      ],
      makeBondCashflowRows(1200),
    ),
  base_case_waterfall_trace: () =>
    previewPayload(
      "base_case_waterfall_trace",
      ["period", "step", "tranche", "due", "paid", "shortfall"],
      makeWaterfallTraceRows(360),
    ),
  base_case_trigger_state_history: () =>
    previewPayload(
      "base_case_trigger_state_history",
      ["period", "trigger_id", "state", "cumulative_loss_pct", "delinquency_pct"],
      makeTriggerStateRows(360),
    ),
  base_case_tranche_risk_summary: () =>
    previewPayload(
      "base_case_tranche_risk_summary",
      [
        "tranche_id",
        "original_face",
        "wal_years",
        "credit_enhancement_pct",
        "yield_to_maturity_pct",
        "principal_loss",
        "interest_default",
      ],
      makeTrancheRiskRows(),
    ),
  base_case_credit_enhancement: () =>
    previewPayload(
      "base_case_credit_enhancement",
      ["tranche_id", "credit_enhancement_pct", "subordination_pct"],
      makeTrancheRiskRows().map((r) => ({
        tranche_id: r.tranche_id,
        credit_enhancement_pct: r.credit_enhancement_pct,
        subordination_pct: r.credit_enhancement_pct,
      })),
    ),
  base_case_carry_tieout: () =>
    previewPayload(
      "base_case_carry_tieout",
      ["pool_yield_pct", "weighted_coupon_pct", "implied_residual_yield_pct", "status"],
      [
        {
          pool_yield_pct: 6.12,
          weighted_coupon_pct: 5.62,
          implied_residual_yield_pct: 11.8,
          status: "OK",
        },
      ],
    ),
  base_case_pac_tac_diagnostics: () =>
    previewPayload(
      "base_case_pac_tac_diagnostics",
      ["tranche_id", "period", "scheduled_balance", "actual_balance", "schedule_miss_bps"],
      makePacTacRows(),
    ),
  base_case_decrement_table: () =>
    previewPayload(
      "base_case_decrement_table",
      ["psa_speed", "wal_a1_years", "wal_b1_years"],
      [
        { psa_speed: 100, wal_a1_years: 5.1, wal_b1_years: 7.8 },
        { psa_speed: 150, wal_a1_years: 4.2, wal_b1_years: 6.8 },
        { psa_speed: 250, wal_a1_years: 3.0, wal_b1_years: 5.2 },
      ],
    ),
  base_case_stress_matrix: () =>
    previewPayload(
      "base_case_stress_matrix",
      ["scenario", "cum_loss_pct", "a1_loss_pct", "b1_loss_pct", "r_loss_pct"],
      [
        { scenario: "Base", cum_loss_pct: 1.5, a1_loss_pct: 0, b1_loss_pct: 0, r_loss_pct: 4.25 },
        { scenario: "1.5x", cum_loss_pct: 2.25, a1_loss_pct: 0, b1_loss_pct: 0.4, r_loss_pct: 6.1 },
        { scenario: "2.0x", cum_loss_pct: 3.0, a1_loss_pct: 0, b1_loss_pct: 1.2, r_loss_pct: 8.4 },
      ],
    ),
  base_case_structure_composition: () =>
    previewPayload(
      "base_case_structure_composition",
      ["tranche_id", "size_pct_pool", "kind"],
      [
        { tranche_id: "A1", size_pct_pool: 71.43, kind: "CASH_PAY" },
        { tranche_id: "B1", size_pct_pool: 19.05, kind: "CASH_PAY" },
        { tranche_id: "R", size_pct_pool: 9.52, kind: "RESIDUAL" },
      ],
    ),
  base_case_solver_iterations: () =>
    previewPayload(
      "base_case_solver_iterations",
      ["iteration", "objective_value_pct", "gap_to_target_bps", "feasible"],
      makeSolverIterations(),
    ),
  base_case_solver_selected_solution: () =>
    previewPayload(
      "base_case_solver_selected_solution",
      ["knob_id", "was_pct", "now_pct", "delta_bps"],
      makeSolverSelectedSolution(),
    ),
  base_case_solver_ce_ladder: () =>
    previewPayload(
      "base_case_solver_ce_ladder",
      ["tranche_id", "required_ce_pct", "achieved_ce_pct", "gap_pct"],
      makeSolverCeLadder(),
    ),
};

export async function mountApiMocks(page: Page) {
  await page.route("**/api/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const path = url.pathname;

    if (path === "/api/runs-list") {
      return json(route, runListFixture);
    }

    if (path === "/api/uploads") {
      return json(route, { items: [] });
    }

    if (path === "/api/deals/pools") {
      return json(route, { items: [] });
    }

    if (path === "/api/runs/run_struct_001/artifacts") {
      return json(route, structuredArtifactsFixture);
    }

    if (path === "/api/runs/run_struct_002/artifacts") {
      // Same artifact catalog so the compare-run flow has both base + compare.
      return json(route, { run_id: "run_struct_002", artifacts: [...structuredArtifacts] });
    }

    const previewMatch = path.match(/^\/api\/runs\/(run_struct_\d+)\/preview\/(.+)$/);
    if (previewMatch) {
      const artifact = previewMatch[2];
      const handler = PREVIEW_HANDLERS[artifact];
      if (handler) {
        return json(route, handler());
      }
    }

    if (path === "/api/deals/deal_abc") {
      return json(route, {
        deal_id: "deal_abc",
        deal_name: "Prime 2026-1",
        schema_version: "v1",
        saved_at: "2026-05-02T10:00:00Z",
        ir: {
          bonds: [
            { name: "A1", kind: "CASH_PAY" },
            { name: "B1", kind: "CASH_PAY" },
            { name: "R", kind: "RESIDUAL" },
          ],
        },
      });
    }

    // Avoid accidental backend dependency in e2e harness.
    return json(route, { detail: `Unhandled mock path: ${path}` }, 501);
  });
}

export async function setSessionState(page: Page, state: Record<string, unknown>) {
  await page.addInitScript((seed) => {
    window.sessionStorage.setItem("bma_cfengine_session", JSON.stringify(seed));
  }, state);
}
