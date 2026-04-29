/**
 * Analytic pool cashflow projection for the live carry tie-out banner.
 *
 * This module is **pure TypeScript with no engine round-trip**. It runs
 * on every PropertyPanel keystroke, so it has to be fast and
 * dependency-free. The trade-off is that the math is intentionally
 * simpler than the BMA cashflow engine:
 *
 *   - Constant CPR (no PSA ramp, no seasoning vector).
 *   - Level-pay scheduled principal (annuity formula).
 *   - No defaults / no severity in iteration 1 (CDR/severity are
 *     accepted but ignored). Loss modeling will flow through the
 *     post-run engine-truth carry tie-out (Phase 4) once a base run
 *     exists; the live banner is for steering, not absolute truth.
 *
 * This is the same simplification industry tools (Bloomberg's quick
 * yield, Excel "Goal Seek" carry calculators) use for live editing.
 * The post-run PV-YTM tie-out (Phase 4, already shipped) is the
 * engine-truth check.
 */

export interface PoolInputs {
  /** Current pool balance in dollars. */
  balance: number;
  /** Gross weighted-average coupon, percent (e.g., 6.5 means 6.5%). */
  wac_pct: number;
  /** Servicing fee in percent, deducted from gross to produce net yield. */
  servicing_pct: number;
  /** Remaining term, months. Used as the amortization horizon. */
  remaining_term_months: number;
  /** Constant Prepayment Rate, annual percent (e.g., 6.0 for 6% CPR). */
  cpr_pct: number;
}

export interface PoolPeriodRow {
  /** 1-indexed period (month). */
  period: number;
  /** Beginning-of-period balance. */
  balance_bop: number;
  /** Interest paid this period (gross). */
  interest_gross: number;
  /** Servicing fee this period. */
  servicing: number;
  /** Net interest (gross - servicing) for tie-out math. */
  interest_net: number;
  /** Scheduled principal this period. */
  scheduled_principal: number;
  /** Voluntary prepayment (CPR-driven) this period. */
  prepay_principal: number;
  /** Total principal (scheduled + prepay). */
  total_principal: number;
}

export interface PoolProjection {
  rows: PoolPeriodRow[];
  /** Net yield (CBE-equivalent annualized) used for carry math. */
  net_yield_pct: number;
  /** Modified duration in years (Macaulay / (1 + y/12)). */
  modified_duration_years: number;
  /** Convexity (sum of t*(t+1)*PV / discounted-PV / (1+y/12)^2 / 144). */
  convexity_years_squared: number;
  /** Weighted average life in years (years to half pay-down). */
  weighted_average_life_years: number;
  /** Final-period principal recovered (sanity check; should equal balance). */
  total_principal_paid: number;
}

/**
 * Annual to monthly rate: (1 + r_annual)^(1/12) - 1.
 *
 * For a fixed-rate mortgage we use the simple monthly = annual/12
 * convention (industry standard; matches BMA engine `period_factor=1/12`).
 * For prepayment CPR we use the geometric SMM = 1 - (1 - CPR)^(1/12)
 * convention.
 */
function monthlyMortgageRate(annual_pct: number): number {
  return (annual_pct / 100) / 12;
}

function cprToSmm(cpr_pct: number): number {
  if (cpr_pct <= 0) return 0;
  if (cpr_pct >= 100) return 1;
  return 1 - Math.pow(1 - cpr_pct / 100, 1 / 12);
}

/**
 * Project pool cashflows under constant-CPR amortization.
 *
 * The schedule is computed via the standard mortgage payment
 * formula on the *un-prepaid* balance, then prepayment is applied as
 * an SMM cut on the post-payment balance each month. This matches
 * industry practice for analytic projections.
 */
export function projectPoolAtBaseCPR(inputs: PoolInputs): PoolProjection {
  const { balance, wac_pct, servicing_pct, remaining_term_months, cpr_pct } = inputs;
  if (balance <= 0 || remaining_term_months <= 0) {
    return {
      rows: [],
      net_yield_pct: Math.max(wac_pct - servicing_pct, 0),
      modified_duration_years: 0,
      convexity_years_squared: 0,
      weighted_average_life_years: 0,
      total_principal_paid: 0,
    };
  }
  const r = monthlyMortgageRate(wac_pct);
  const smm = cprToSmm(cpr_pct);
  const svc_monthly = monthlyMortgageRate(servicing_pct);
  // Annuity payment (level-pay) at the gross rate.
  const n = remaining_term_months;
  const A = balance;
  const pmt =
    r === 0 ? A / n : (A * r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1);

  const rows: PoolPeriodRow[] = [];
  let bop = balance;
  let total_prin = 0;
  for (let t = 1; t <= n; t++) {
    if (bop <= 1e-6) break;
    const interest_gross = bop * r;
    const servicing = bop * svc_monthly;
    const interest_net = interest_gross - servicing;
    const scheduled_prin = Math.max(Math.min(pmt - interest_gross, bop), 0);
    const after_sched = bop - scheduled_prin;
    const prepay_prin = after_sched * smm;
    const total_principal = scheduled_prin + prepay_prin;
    rows.push({
      period: t,
      balance_bop: bop,
      interest_gross,
      servicing,
      interest_net,
      scheduled_principal: scheduled_prin,
      prepay_principal: prepay_prin,
      total_principal,
    });
    total_prin += total_principal;
    bop = after_sched - prepay_prin;
  }

  // Net yield approx: WAC - servicing, expressed as annual percent.
  const net_yield_pct = Math.max(wac_pct - servicing_pct, 0);
  const y_monthly = monthlyMortgageRate(net_yield_pct);

  // Discount the *net* cashflow stream (net interest + total principal)
  // at the net yield to compute Macaulay/modified duration and convexity.
  const { mac_dur_months, convexity_months_sq } = discountStream(
    rows.map((row) => ({ t: row.period, cf: row.interest_net + row.total_principal })),
    y_monthly,
  );
  const mac_dur_years = mac_dur_months / 12;
  const modified_duration_years = mac_dur_years / (1 + y_monthly);
  const convexity_years_squared = convexity_months_sq / 144;

  // WAL: Σ(t * principal_t) / Σ(principal_t), then convert months -> years.
  const wal_months =
    total_prin > 0
      ? rows.reduce((s, row) => s + row.period * row.total_principal, 0) / total_prin
      : 0;

  return {
    rows,
    net_yield_pct,
    modified_duration_years,
    convexity_years_squared,
    weighted_average_life_years: wal_months / 12,
    total_principal_paid: total_prin,
  };
}

/**
 * Compute Macaulay duration (months) and convexity (months^2) of an
 * arbitrary cashflow stream discounted at the supplied monthly rate.
 *
 * Returned values are integer-period weighted; conversion to years and
 * to modified duration happens at the call site.
 */
export function discountStream(
  cashflows: { t: number; cf: number }[],
  y_monthly: number,
): { mac_dur_months: number; convexity_months_sq: number; total_pv: number } {
  let total_pv = 0;
  let weighted_t = 0;
  let weighted_t_sq = 0;
  for (const { t, cf } of cashflows) {
    if (cf === 0) continue;
    const df = Math.pow(1 + y_monthly, -t);
    const pv = cf * df;
    total_pv += pv;
    weighted_t += t * pv;
    weighted_t_sq += (t * t + t) * pv;
  }
  if (total_pv <= 0) {
    return { mac_dur_months: 0, convexity_months_sq: 0, total_pv: 0 };
  }
  const mac_dur_months = weighted_t / total_pv;
  // Convexity formula: Σ((t² + t) * CF * df) / total_pv / (1+y)²
  const convexity_months_sq =
    weighted_t_sq / total_pv / Math.pow(1 + y_monthly, 2);
  return { mac_dur_months, convexity_months_sq, total_pv };
}
