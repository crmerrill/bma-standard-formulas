/**
 * Static carry tie-out engine.
 *
 * Pure-TypeScript companion to the post-run engine-truth tie-out
 * (`src/bma_standard_formulas/deals/carry_tieout.py`). This module
 * lets PropertyPanel and IrPreviewPanel render a *live* warn/block
 * banner without any engine round-trip: it runs on every keystroke
 * and reports whether the structure is economically sound based on
 * static (analytic) durations and a back-solved residual yield.
 *
 * Methodology (mirrors `engine_completeness_and_carry_tieout.plan.md`):
 *
 *   - Project the pool under constant CPR (light analytic
 *     amortization in `poolProjection.ts`).
 *
 *   - For each cash-paying tranche, allocate principal by waterfall
 *     priority order (sequential in iteration 1) and compute its
 *     Macaulay/modified duration and convexity under par pricing
 *     (= bond coupon as the discount rate).
 *
 *   - Back-solve the implied residual yield from the carry identity:
 *
 *       pool_yield * pool_dur * pool_bal
 *         = Σ(notional_i * coupon_i * dur_i)
 *         + resid_yield * resid_dur * resid_bal
 *
 *     Re-arranged:
 *
 *       resid_yield = (pool_yield * pool_dur * pool_bal
 *                      - Σ(notional_i * coupon_i * dur_i))
 *                     / (resid_dur * resid_bal)
 *
 *   - Three measures are exposed: notional-weighted (context only,
 *     no time value), duration-weighted (live status fallback), and
 *     convexity-adjusted (default live status driver).
 *
 * Status thresholds match the plan's locked defaults:
 *
 *   - OK   : implied residual yield ∈ [5%, 35%].
 *   - WARN : implied yield in [0%, 5%) or (35%, 50%].
 *   - BLOCK: implied yield < 0% or > 50%.
 */

import {
  projectPoolAtBaseCPR,
  discountStream,
  type PoolInputs,
  type PoolProjection,
} from "./poolProjection";

export interface BondInput {
  /** Bond identifier (e.g. "A", "M-1"). */
  name: string;
  /** Bond size in dollars. */
  notional: number;
  /** Bond coupon, annual percent (e.g., 5.5 for 5.5%). */
  coupon_pct: number;
  /** Used to skip residual classes from the regular tranche stack. */
  tranche_type: string;
  /** PIK bonds accrue rather than pay cash interest; we still include
   *  them in the carry math at their stated coupon as the implied cost
   *  of capital, since the residual ultimately bears the PIK accretion. */
  pay_mode?: "CASH_PAY" | "PIK";
}

export interface CarryTieOutInputs {
  pool: PoolInputs;
  bonds: BondInput[];
  /** Optional override of the warn/block thresholds (basis points around
   *  the [5%, 35%] band). Currently unused -- thresholds are status
   *  bands on the implied yield itself, not gap to a target. Reserved
   *  for the IR-persisted user override planned in Phase 5. */
  threshold_overrides?: {
    ok_band_low_pct?: number;
    ok_band_high_pct?: number;
    warn_floor_pct?: number;
    warn_ceiling_pct?: number;
  };
}

export interface TrancheCarryRow {
  name: string;
  notional: number;
  coupon_pct: number;
  duration_years: number;
  convexity_years_squared: number;
  /** Share of the *bond* universe (notional / Σ notional_bond). */
  weight: number;
}

export type CarryStatus = "OK" | "WARN" | "BLOCK";

export interface CarryTieOutResult {
  pool_balance: number;
  pool_net_yield_pct: number;
  pool_duration_years: number;
  pool_convexity_years_squared: number;
  pool_wal_years: number;

  bonds_total_notional: number;
  residual_balance: number;
  residual_duration_years: number;
  residual_convexity_years_squared: number;

  tranches: TrancheCarryRow[];

  /** Notional weighted -- context only, ignores time value. */
  implied_residual_yield_notional_pct: number;
  /** Duration-weighted -- live fallback driver. */
  implied_residual_yield_duration_pct: number;
  /** Convexity-adjusted -- default live driver. */
  implied_residual_yield_convexity_adjusted_pct: number;

  status: CarryStatus;
  reason: string;
  /** True when there are no cash-paying bonds, no residual, or pool
   *  has zero balance -- carry math is meaningless and the banner
   *  should suppress its output instead of showing a misleading
   *  status. */
  is_degenerate: boolean;
}

/**
 * Default OK/WARN/BLOCK bands for the implied residual yield, locked
 * by `engine_completeness_and_carry_tieout.plan.md`.
 */
const DEFAULT_BANDS = {
  ok_low_pct: 5,
  ok_high_pct: 35,
  warn_floor_pct: 0,
  warn_ceiling_pct: 50,
} as const;

const RESIDUAL_TRANCHE_TYPES = new Set([
  "RESIDUAL",
  "PSEUDO",
]);

const ZERO_RATE_TYPES = new Set(["PSEUDO"]);

export function computeStaticCarryTieOut(
  inputs: CarryTieOutInputs,
): CarryTieOutResult {
  const projection = projectPoolAtBaseCPR(inputs.pool);

  const allBonds = inputs.bonds.filter(
    (b) => !ZERO_RATE_TYPES.has(b.tranche_type),
  );
  const cashBonds = allBonds.filter(
    (b) => !RESIDUAL_TRANCHE_TYPES.has(b.tranche_type) && b.notional > 0,
  );
  const totalBondNotional = sum(cashBonds.map((b) => b.notional));
  const residualBalance = Math.max(
    inputs.pool.balance - totalBondNotional,
    0,
  );

  const isDegenerate =
    inputs.pool.balance <= 0 ||
    cashBonds.length === 0 ||
    residualBalance <= 0;

  // Allocate pool principal sequentially across the cash bonds (in the
  // order they appear in the IR -- matches the most common waterfall
  // and is good enough for live editing). The residual gets the
  // tail. Each tranche's duration is computed against its own
  // allocation stream, discounted at its coupon (par pricing).
  const allocations = allocatePrincipalSequentially(
    projection,
    cashBonds.map((b) => b.notional),
  );

  const tranches: TrancheCarryRow[] = cashBonds.map((bond, idx) => {
    const allocation = allocations[idx];
    const coupon_monthly = (bond.coupon_pct / 100) / 12;
    const stream = _toCashflowStream(allocation.flow, coupon_monthly);
    const { mac_dur_months, convexity_months_sq } = discountStream(
      stream,
      coupon_monthly,
    );
    const duration_years =
      stream.length === 0
        ? 0
        : (mac_dur_months / 12) / (1 + coupon_monthly);
    const convexity_years_squared = convexity_months_sq / 144;
    return {
      name: bond.name,
      notional: bond.notional,
      coupon_pct: bond.coupon_pct,
      duration_years,
      convexity_years_squared,
      weight: totalBondNotional > 0 ? bond.notional / totalBondNotional : 0,
    };
  });

  // Residual receives whatever pool cashflows aren't paid to bonds.
  // The pool's balance-weighted duration is the sum of all pieces:
  //
  //   pool_dur * pool_bal
  //     = Σ(bond_dur_i * bond_bal_i) + resid_dur * resid_bal
  //
  // Re-arrange to back out resid_dur. This identity holds for static
  // analytic projections; engine-truth durations may differ and are
  // surfaced post-run via the Python carry tie-out.
  const pool_dollar_dur =
    projection.modified_duration_years * inputs.pool.balance;
  const bond_dollar_dur = sum(
    tranches.map((t) => t.duration_years * t.notional),
  );
  const residual_duration_years = Math.max(
    (pool_dollar_dur - bond_dollar_dur) / Math.max(residualBalance, 1),
    0.25,
  );
  // Same identity applies to convexity (additive in dollars, not %).
  const pool_dollar_cvx =
    projection.convexity_years_squared * inputs.pool.balance;
  const bond_dollar_cvx = sum(
    tranches.map((t) => t.convexity_years_squared * t.notional),
  );
  const residual_convexity_years_squared = Math.max(
    (pool_dollar_cvx - bond_dollar_cvx) / Math.max(residualBalance, 1),
    0,
  );

  // ------------------------------------------------------------------
  // Three back-solved residual yield measures.
  // ------------------------------------------------------------------
  // 1) Notional-weighted (context only).
  const sum_bond_coupon_notional = sum(
    cashBonds.map((b) => b.notional * (b.coupon_pct / 100)),
  );
  const pool_yield_dollars =
    inputs.pool.balance * (projection.net_yield_pct / 100);
  const implied_residual_yield_notional_pct = isDegenerate
    ? Number.NaN
    : ((pool_yield_dollars - sum_bond_coupon_notional) / residualBalance) * 100;

  // 2) Duration-weighted.
  const sum_bond_couponXdur = sum(
    tranches.map((t) => t.notional * (t.coupon_pct / 100) * t.duration_years),
  );
  const pool_yieldXdur =
    (projection.net_yield_pct / 100) *
    projection.modified_duration_years *
    inputs.pool.balance;
  const implied_residual_yield_duration_pct = isDegenerate
    ? Number.NaN
    : ((pool_yieldXdur - sum_bond_couponXdur) /
        (residual_duration_years * residualBalance)) *
      100;

  // 3) Convexity-adjusted (apply ½ * convexity * Δy² correction at a
  //    100 bps shock, summed across both sides).
  const SHOCK = 0.01; // 100 bps
  const pool_convex_adj =
    0.5 *
    projection.convexity_years_squared *
    Math.pow(SHOCK, 2) *
    inputs.pool.balance;
  const bond_convex_adj = sum(
    tranches.map(
      (t) =>
        0.5 *
        t.convexity_years_squared *
        Math.pow(SHOCK, 2) *
        t.notional,
    ),
  );
  const implied_residual_yield_convexity_adjusted_pct = isDegenerate
    ? Number.NaN
    : ((pool_yieldXdur + pool_convex_adj -
        sum_bond_couponXdur -
        bond_convex_adj) /
        (residual_duration_years * residualBalance)) *
      100;

  const primaryYield = implied_residual_yield_convexity_adjusted_pct;
  const { status, reason } = classifyImpliedYield(
    primaryYield,
    isDegenerate,
    inputs.threshold_overrides ?? {},
  );

  return {
    pool_balance: inputs.pool.balance,
    pool_net_yield_pct: projection.net_yield_pct,
    pool_duration_years: projection.modified_duration_years,
    pool_convexity_years_squared: projection.convexity_years_squared,
    pool_wal_years: projection.weighted_average_life_years,
    bonds_total_notional: totalBondNotional,
    residual_balance: residualBalance,
    residual_duration_years,
    residual_convexity_years_squared,
    tranches,
    implied_residual_yield_notional_pct,
    implied_residual_yield_duration_pct,
    implied_residual_yield_convexity_adjusted_pct,
    status,
    reason,
    is_degenerate: isDegenerate,
  };
}

function classifyImpliedYield(
  yieldPct: number,
  isDegenerate: boolean,
  overrides: NonNullable<CarryTieOutInputs["threshold_overrides"]>,
): { status: CarryStatus; reason: string } {
  if (isDegenerate || !Number.isFinite(yieldPct)) {
    return {
      status: "OK",
      reason: "Not enough structure to evaluate carry yet.",
    };
  }
  const ok_low = overrides.ok_band_low_pct ?? DEFAULT_BANDS.ok_low_pct;
  const ok_high = overrides.ok_band_high_pct ?? DEFAULT_BANDS.ok_high_pct;
  const warn_floor =
    overrides.warn_floor_pct ?? DEFAULT_BANDS.warn_floor_pct;
  const warn_ceiling =
    overrides.warn_ceiling_pct ?? DEFAULT_BANDS.warn_ceiling_pct;
  if (yieldPct < warn_floor) {
    return {
      status: "BLOCK",
      reason:
        `Implied residual yield ${fmtPct(yieldPct)} is negative — the bond stack ` +
        `over-couponed against the pool. The residual class would need a ` +
        `negative yield to make the carry balance.`,
    };
  }
  if (yieldPct > warn_ceiling) {
    return {
      status: "BLOCK",
      reason:
        `Implied residual yield ${fmtPct(yieldPct)} is unrealistically high — ` +
        `bond stack is under-coupon, so the residual would need an unreasonable ` +
        `return to balance.`,
    };
  }
  if (yieldPct < ok_low) {
    return {
      status: "WARN",
      reason:
        `Implied residual yield ${fmtPct(yieldPct)} is below ${fmtPct(ok_low)} — ` +
        `bond stack is rich. Verify the deal can support its coupons.`,
    };
  }
  if (yieldPct > ok_high) {
    return {
      status: "WARN",
      reason:
        `Implied residual yield ${fmtPct(yieldPct)} is above ${fmtPct(ok_high)} — ` +
        `bond stack is cheap. Tighter coupons or a thinner residual would be ` +
        `more economic.`,
    };
  }
  return {
    status: "OK",
    reason:
      `Implied residual yield ${fmtPct(yieldPct)} is within the typical ` +
      `${fmtPct(ok_low)}–${fmtPct(ok_high)} band.`,
  };
}

/**
 * Allocate pool principal across an ordered list of tranches with the
 * given notionals. Each tranche absorbs principal until its balance
 * reaches zero, then the next one starts. Interest each period is the
 * tranche's beginning-of-period balance times its (later-applied)
 * coupon -- the carry function multiplies by coupon at allocation
 * time so we just emit the principal stream and the implied interest
 * accrual base here.
 */
interface AllocatedFlowRow {
  period: number;
  /** Principal received this period. */
  principal: number;
  /** Interest received this period. */
  interest: number;
}

function allocatePrincipalSequentially(
  projection: PoolProjection,
  notionals: number[],
): { flow: AllocatedFlowRow[] }[] {
  const allocations: { flow: AllocatedFlowRow[]; balance: number; notional: number }[] =
    notionals.map((n) => ({ flow: [], balance: n, notional: n }));
  // For every period, every still-outstanding tranche gets a row -- it
  // earns interest on its full BOP balance even when a more-senior
  // tranche is consuming all the principal. The discount stream the
  // caller builds via _toCashflowStream multiplies BOP balance by
  // coupon_monthly, so capturing the BOP balance per period is
  // sufficient to reconstruct the correct interest cashflow.
  //
  // Principal is allocated sequentially: each period's principal
  // first fills tranche 0 to zero, then tranche 1, etc. This matches
  // the most common waterfall and is good enough for the live banner
  // (the post-run engine-truth tie-out handles non-sequential
  // structures).
  for (const row of projection.rows) {
    let remainingPrincipal = row.total_principal;
    for (const alloc of allocations) {
      if (alloc.balance <= 1e-6) {
        continue;
      }
      const bop_balance = alloc.balance;
      let principalThis = 0;
      if (remainingPrincipal > 1e-6) {
        principalThis = Math.min(remainingPrincipal, alloc.balance);
        alloc.balance -= principalThis;
        remainingPrincipal -= principalThis;
      }
      alloc.flow.push({
        period: row.period,
        principal: principalThis,
        interest: bop_balance,
      });
    }
  }
  return allocations.map((a) => ({ flow: a.flow }));
}

/**
 * Wrapper that converts the raw allocation stream produced by
 * `allocatePrincipalSequentially` into a discountable cash-flow series
 * for a specific bond's coupon. Kept here so the awkward "interest =
 * bop_balance, multiply by coupon_monthly" trick stays a private
 * implementation detail of this file.
 */
export function _toCashflowStream(
  flow: { period: number; principal: number; interest: number }[],
  coupon_monthly: number,
): { t: number; cf: number }[] {
  return flow.map((row) => ({
    t: row.period,
    cf: row.principal + row.interest * coupon_monthly,
  }));
}

function sum(values: number[]): number {
  let s = 0;
  for (const v of values) s += v;
  return s;
}

function fmtPct(v: number): string {
  if (!Number.isFinite(v)) return "n/a";
  return `${v.toFixed(2)}%`;
}
