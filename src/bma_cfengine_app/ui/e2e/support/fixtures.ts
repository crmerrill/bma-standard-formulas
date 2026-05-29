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
    total_balance: 2100000000,
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
    total_balance: 2100000000,
    wac: 6.12,
    deal_id: "deal_abc",
    deal_name: "Prime 2026-1",
  },
];

export const structuredArtifactsFixture = {
  run_id: "run_struct_001",
  artifacts: ["base_case_bond_cashflows"],
};

export function makeBondCashflowRows(periods = 1200) {
  const rows: Array<Record<string, unknown>> = [];
  for (let i = 1; i <= periods; i += 1) {
    rows.push({
      period: i,
      tranche_id: "A1",
      total_principal: Math.max(0, 2500000 - i * 1500),
      interest_paid: Math.max(0, 850000 - i * 500),
      writedown: i % 240 === 0 ? 2000 : 0,
      end_balance: Math.max(0, 150000000 - i * 90000),
      interest_shortfall: i % 180 === 0 ? 350 : 0,
    });
    rows.push({
      period: i,
      tranche_id: "B1",
      total_principal: Math.max(0, 1500000 - i * 900),
      interest_paid: Math.max(0, 610000 - i * 350),
      writedown: i % 180 === 0 ? 3500 : 0,
      end_balance: Math.max(0, 90000000 - i * 75000),
      interest_shortfall: i % 120 === 0 ? 500 : 0,
    });
  }
  return rows;
}
