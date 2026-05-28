/**
 * Shared TypeScript IR type definitions for the Structuring Studio.
 *
 * These types represent the JSON-serializable DealDefinitionIR that flows
 * between the Blockly workspace, the backend API, and the save/load paths.
 * They are a structural subset of the Python DealDefinition Pydantic schema.
 *
 * RG10: Centralised here so irGenerator.ts, irToBlocklyState.ts, PropertyPanel.tsx,
 * and test files share one source of truth rather than maintaining divergent copies.
 */

export type TrancheKind =
  | "CASH_PAY"
  | "PAC"
  | "TAC"
  | "IO"
  | "PO"
  | "Z"
  | "RESIDUAL"
  | "PSEUDO";

export interface TrancheRelation {
  relation_type: string;
  targets: string[];
  weights?: number[] | null;
  leverage?: number | null;
  cap?: number | null;
  floor?: number | null;
  description?: string;
}

export interface RateScheduleEntry {
  from_period: number;
  rate: number;
}

export type RateOrSchedule = number | RateScheduleEntry[];

export interface BondDefIR {
  name: string;
  kind: TrancheKind;
  group_id?: string | null;
  coupon: RateOrSchedule;
  notional_pct_of_collateral: number;
  notional: number;
  is_bond: boolean;
  is_pseudo: boolean;
  coupon_type: string;
  index_name: string | null;
  margin: RateOrSchedule | null;
  pay_mode: "CASH_PAY" | "PIK";
  schedule_model_type: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR" | null;
  schedule_priority_tier: number | null;
  schedule_depends_on: string | null;
  schedule_speed_low: number | null;
  schedule_speed_high: number | null;
  schedule_custom_vector: string | null;
  schedule_contract: Array<{ period: number; target_principal: number }>;
  schedule_tolerance_bps: number | null;
  schedule_derivation?: Record<string, unknown> | null;
  relations: TrancheRelation[];
  z_accrual_enabled: boolean;
  z_release_trigger: string | null;
  /** Phase 6: NLA tracking fields */
  nla_starting_balance?: number | null;
  required_subordination_pct?: number | null;
  seniority?: number | null;
}

export interface AccountMinimumScheduleEntry {
  period: number;
  minimum_balance: number;
}

export interface AccountDefIR {
  name: string;
  account_category: string;
  starting_amount: number;
  starting_pct: number | null;
  starting_basis: string;
  /** Phase 7: funding-account accumulation schedule */
  minimum_schedule?: AccountMinimumScheduleEntry[] | null;
}

export interface FeeDefIR {
  name: string;
  basis_type: string;
  amount: number;
  rate: number | null;
  frequency: string;
}

export interface TriggerNodeIR {
  name: string;
  metric_type: string;
  threshold_value: number;
  /** Phase 9: rolling-window trigger */
  window_periods?: number | null;
  comparison?: string | null;
}

export interface CalculationNodeIR {
  name: string;
  expression: string;
  description?: string;
}

export interface RuleNodeIR {
  rule_id: string;
  rule_type: string;
  order: number;
  from_sources: string[];
  to_targets: string[];
  payment_style: string;
  max_amount_fixed: number | null;
  condition_trigger: string | null;
  condition_invert: boolean;
  group_id?: string | null;
  cap_mode?: string | null;
  coverage_mode?: string | null;
  target_weights?: number[] | null;
}

export interface CollateralGroupDefIR {
  group_id: string;
  label: string;
  description: string;
}

export interface DealDefinitionIR {
  schema_version: string;
  deal_name: string;
  /** Phase 8 */
  series_id?: string | null;
  bonds: BondDefIR[];
  accounts: AccountDefIR[];
  fees: FeeDefIR[];
  triggers: TriggerNodeIR[];
  calculations?: CalculationNodeIR[];
  waterfall_rules: RuleNodeIR[];
  collateral_groups: CollateralGroupDefIR[];
  deal_knobs: Record<string, number | string | boolean>;
  /** Phase 9 */
  deal_state_trigger?: string | null;
  initial_deal_state?: string | null;
}
