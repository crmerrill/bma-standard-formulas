/**
 * E2E fixtures grounded in real RMBS/CLO structuring concepts.
 *
 * Sources used to design these fixtures so journeys reflect real practice:
 *   - Peak53 Partners, "RMBS Primer" (subordination, structural protection)
 *   - Angel Oak Capital, "Securitization 101" (senior-sub waterfalls, residual)
 *   - Dutch RMBS Primer (reserve account sizing, PDL, subordination)
 *   - RBA, "Cash Flow Waterfall Reporting Template" (income/principal/chargeoff
 *     sub-waterfalls, determination date)
 *   - RBC Wealth Management, "Investor's Guide to MBS/CMOs" (PAC schedules,
 *     sequential pay)
 *   - Guggenheim, "Understanding CLOs" (waterfall + coverage tests)
 *   - AnalystPrep FRM Part II, "Structured Credit Risk" (OC tests, stepdown
 *     gating, attachment/detachment points)
 *   - GitHub Diljit22/rmbs (loan pool → tranche waterfall demo)
 *
 * Fixtures encode a small-but-realistic three-tranche senior-sub deal:
 *   A1 (senior, ~70%)  →  B1 (mezz, ~20%)  →  R (residual, ~10%)
 * Cumulative losses are injected over time so:
 *   1. The mezz tranche absorbs losses first (Peak53 §"Structural")
 *   2. Senior CE > Mezz CE > Residual (Dutch primer §4.6.1)
 *   3. A stepdown trigger breaches mid-life (AnalystPrep §"Stepdown")
 *   4. PAC schedule misses appear under heavy prepay variance (RBC §"PAC")
 */

export const runListFixture = [
  {
    run_id: "run_port_001",
    status: "completed",
    created_at: "2026-05-01T10:00:00Z",
    run_type: "portfolio",
    run_kind: "deal_run",
    loan_count: 52411,
    group_count: 7,
    scenario_names: ["Base Case"],
    elapsed_seconds: 12.45,
    total_balance: 2_100_000_000,
    wac: 6.12,
    deal_id: null,
    deal_name: null,
  },
  {
    run_id: "run_struct_001",
    status: "completed",
    created_at: "2026-05-02T10:00:00Z",
    run_type: "structured_deal",
    run_kind: "solver",
    loan_count: 52411,
    group_count: 0,
    scenario_names: ["Base Case"],
    elapsed_seconds: 45.67,
    total_balance: 2_100_000_000,
    wac: 6.12,
    deal_id: "deal_abc",
    deal_name: "Prime 2026-1",
  },
  {
    run_id: "run_struct_002",
    status: "completed",
    created_at: "2026-05-03T11:00:00Z",
    run_type: "structured_deal",
    run_kind: "solver",
    loan_count: 52411,
    group_count: 0,
    scenario_names: ["Stress 2x Loss"],
    elapsed_seconds: 50.12,
    total_balance: 2_100_000_000,
    wac: 6.12,
    deal_id: "deal_abc",
    deal_name: "Prime 2026-1",
  },
];

/** Structured deal artifact catalog. Each name maps to a /preview endpoint. */
export const structuredArtifacts = [
  "base_case_bond_cashflows",
  "base_case_waterfall_trace",
  "base_case_trigger_state_history",
  "base_case_tranche_risk_summary",
  "base_case_credit_enhancement",
  "base_case_carry_tieout",
  "base_case_pac_tac_diagnostics",
  "base_case_decrement_table",
  "base_case_stress_matrix",
  "base_case_structure_composition",
  "base_case_solver_iterations",
  "base_case_solver_selected_solution",
  "base_case_solver_ce_ladder",
] as const;

export const structuredArtifactsFixture = {
  run_id: "run_struct_001",
  artifacts: [...structuredArtifacts],
};

/**
 * Bond cashflow rows: senior A1, mezz B1.
 * Senior is loss-protected. Mezz takes the first writedowns (Peak53 §"Structural"
 * "lowest tranche absorbs losses first"). Periodic shortfalls flag interest defaults.
 */
export function makeBondCashflowRows(periods = 1200) {
  const rows: Array<Record<string, unknown>> = [];
  for (let i = 1; i <= periods; i += 1) {
    rows.push({
      period: i,
      tranche_id: "A1",
      total_principal: Math.max(0, 2_500_000 - i * 1_500),
      interest_paid: Math.max(0, 850_000 - i * 500),
      writedown: i > 600 ? 0 : i % 240 === 0 ? 2_000 : 0,
      end_balance: Math.max(0, 150_000_000 - i * 90_000),
      interest_shortfall: i % 180 === 0 ? 350 : 0,
    });
    rows.push({
      period: i,
      tranche_id: "B1",
      total_principal: Math.max(0, 1_500_000 - i * 900),
      interest_paid: Math.max(0, 610_000 - i * 350),
      writedown: i % 180 === 0 ? 3_500 : 0,
      end_balance: Math.max(0, 90_000_000 - i * 75_000),
      interest_shortfall: i % 120 === 0 ? 500 : 0,
    });
  }
  return rows;
}

/**
 * Waterfall trace: per-period payment ledger across the income waterfall
 * (RBA §"Income waterfall"). Senior interest first, then senior principal,
 * then mezz interest, then mezz principal, then residual.
 */
export function makeWaterfallTraceRows(periods = 360) {
  const rows: Array<Record<string, unknown>> = [];
  for (let p = 1; p <= periods; p += 1) {
    const seniorIntDue = 700_000 + (p % 12) * 1_000;
    const seniorIntPaid = seniorIntDue;
    const seniorPrinPaid = Math.max(0, 2_400_000 - p * 1_400);
    const mezzIntDue = 320_000;
    const mezzIntPaid = p > 60 && p < 120 ? mezzIntDue * 0.95 : mezzIntDue;
    const mezzPrinPaid = p > 90 ? Math.max(0, 1_400_000 - p * 800) : 0;
    const residual = Math.max(0, 50_000 - p * 80);
    rows.push({
      period: p,
      step: "PAY_INTEREST_SENIOR",
      tranche: "A1",
      due: seniorIntDue,
      paid: seniorIntPaid,
      shortfall: seniorIntDue - seniorIntPaid,
    });
    rows.push({
      period: p,
      step: "PAY_PRINCIPAL_SENIOR",
      tranche: "A1",
      due: seniorPrinPaid,
      paid: seniorPrinPaid,
      shortfall: 0,
    });
    rows.push({
      period: p,
      step: "PAY_INTEREST_MEZZ",
      tranche: "B1",
      due: mezzIntDue,
      paid: mezzIntPaid,
      shortfall: mezzIntDue - mezzIntPaid,
    });
    rows.push({
      period: p,
      step: "PAY_PRINCIPAL_MEZZ",
      tranche: "B1",
      due: mezzPrinPaid,
      paid: mezzPrinPaid,
      shortfall: 0,
    });
    rows.push({
      period: p,
      step: "PAY_RESIDUAL",
      tranche: "R",
      due: residual,
      paid: residual,
      shortfall: 0,
    });
  }
  return rows;
}

/**
 * Trigger state history: cumulative-loss / delinquency triggered fail in
 * mid-life so stepdown is blocked (Guggenheim §"Coverage tests" / FRM §"OC tests").
 */
export function makeTriggerStateRows(periods = 360) {
  const rows: Array<Record<string, unknown>> = [];
  for (let p = 1; p <= periods; p += 1) {
    const breached = p >= 70 && p <= 130;
    rows.push({
      period: p,
      trigger_id: "STEPDOWN_DELINQUENCY",
      state: breached ? "FAIL" : "PASS",
      cumulative_loss_pct: 0.5 + p * 0.02,
      delinquency_pct: breached ? 5.5 : 2.1,
    });
  }
  return rows;
}

/**
 * Tranche risk summary: shows senior-sub credit enhancement ladder.
 * CE_A1 > CE_B1 > CE_R (Dutch primer §4.6.1, AnalystPrep §"Subordination").
 */
export function makeTrancheRiskRows() {
  return [
    {
      tranche_id: "A1",
      original_face: 1_500_000_000,
      wal_years: 4.2,
      credit_enhancement_pct: 30.0,
      yield_to_maturity_pct: 5.42,
      principal_loss: 0,
      interest_default: false,
    },
    {
      tranche_id: "B1",
      original_face: 400_000_000,
      wal_years: 6.8,
      credit_enhancement_pct: 10.0,
      yield_to_maturity_pct: 6.10,
      principal_loss: 1_500_000,
      interest_default: false,
    },
    {
      tranche_id: "R",
      original_face: 200_000_000,
      wal_years: 9.1,
      credit_enhancement_pct: 0.0,
      yield_to_maturity_pct: 11.85,
      principal_loss: 8_500_000,
      interest_default: false,
    },
  ];
}

/**
 * PAC/TAC diagnostics: schedule miss rows (RBC §"PAC tranches").
 * A small number of misses outside the PAC band illustrate schedule risk.
 */
export function makePacTacRows() {
  return [
    {
      tranche_id: "PAC_A",
      period: 12,
      scheduled_balance: 145_000_000,
      actual_balance: 145_000_000,
      schedule_miss_bps: 0,
    },
    {
      tranche_id: "PAC_A",
      period: 36,
      scheduled_balance: 130_000_000,
      actual_balance: 132_750_000,
      schedule_miss_bps: 21,
    },
    {
      tranche_id: "PAC_A",
      period: 60,
      scheduled_balance: 100_000_000,
      actual_balance: 104_500_000,
      schedule_miss_bps: 45,
    },
  ];
}

/**
 * Solver iterations: trajectory of objective values converging toward target
 * residual yield 12% (BMA solver_ux_design.md §"Auto-Tieout" / Carta best practices).
 */
export function makeSolverIterations() {
  const rows: Array<Record<string, unknown>> = [];
  const target = 12.0;
  let value = 7.4;
  for (let i = 0; i < 18; i += 1) {
    const distance = target - value;
    value += distance * 0.4;
    rows.push({
      iteration: i,
      objective_value_pct: Number(value.toFixed(3)),
      gap_to_target_bps: Math.round(Math.abs(distance) * 100),
      feasible: i > 4,
    });
  }
  return rows;
}

export function makeSolverSelectedSolution() {
  return [
    { knob_id: "class_a_coupon", was_pct: 5.50, now_pct: 5.42, delta_bps: -8 },
    { knob_id: "class_b_coupon", was_pct: 6.25, now_pct: 6.10, delta_bps: -15 },
    { knob_id: "class_c_coupon", was_pct: 7.00, now_pct: 6.95, delta_bps: -5 },
  ];
}

/** Simple CE ladder snapshot for solver_runs tab. */
export function makeSolverCeLadder() {
  return [
    { tranche_id: "A1", required_ce_pct: 27.5, achieved_ce_pct: 30.0, gap_pct: 2.5 },
    { tranche_id: "B1", required_ce_pct: 8.0, achieved_ce_pct: 10.0, gap_pct: 2.0 },
    { tranche_id: "R", required_ce_pct: 0.0, achieved_ce_pct: 0.0, gap_pct: 0.0 },
  ];
}
