import { describe, expect, it } from "vitest";
import {
  projectPoolAtBaseCPR,
  discountStream,
  type PoolInputs,
} from "./poolProjection";

describe("projectPoolAtBaseCPR", () => {
  const basePool: PoolInputs = {
    balance: 100_000_000,
    wac_pct: 6.0,
    servicing_pct: 0.5,
    remaining_term_months: 360,
    cpr_pct: 0,
  };

  it("amortizes a 30-year fixed pool fully over 360 months at 0% CPR", () => {
    const projection = projectPoolAtBaseCPR(basePool);
    expect(projection.rows.length).toBe(360);
    // Total principal returned should equal the starting balance to within
    // a tiny rounding error.
    expect(projection.total_principal_paid).toBeCloseTo(basePool.balance, 0);
    // Final-period balance after pay-down should be ~ zero.
    const last = projection.rows[projection.rows.length - 1];
    expect(last.balance_bop - last.total_principal).toBeLessThan(0.01);
  });

  it("computes net yield as WAC - servicing", () => {
    const projection = projectPoolAtBaseCPR(basePool);
    expect(projection.net_yield_pct).toBe(5.5);
  });

  it("returns positive duration and convexity for a 30y fixed pool", () => {
    const projection = projectPoolAtBaseCPR(basePool);
    // 30-year fixed at 5.5% net yield, 0% CPR: industry duration ~ 11-13y.
    expect(projection.modified_duration_years).toBeGreaterThan(8);
    expect(projection.modified_duration_years).toBeLessThan(15);
    expect(projection.convexity_years_squared).toBeGreaterThan(0);
  });

  it("WAL at 0% CPR is roughly 19-22 years for a 30y fully-amortizing pool", () => {
    const projection = projectPoolAtBaseCPR(basePool);
    expect(projection.weighted_average_life_years).toBeGreaterThan(18);
    expect(projection.weighted_average_life_years).toBeLessThan(22);
  });

  it("higher CPR shortens WAL and reduces duration", () => {
    const slow = projectPoolAtBaseCPR({ ...basePool, cpr_pct: 0 });
    const fast = projectPoolAtBaseCPR({ ...basePool, cpr_pct: 20 });
    expect(fast.weighted_average_life_years).toBeLessThan(
      slow.weighted_average_life_years,
    );
    expect(fast.modified_duration_years).toBeLessThan(
      slow.modified_duration_years,
    );
  });

  it("returns empty projection for zero balance", () => {
    const projection = projectPoolAtBaseCPR({ ...basePool, balance: 0 });
    expect(projection.rows).toEqual([]);
    expect(projection.modified_duration_years).toBe(0);
    expect(projection.weighted_average_life_years).toBe(0);
  });

  it("returns empty projection for zero remaining term", () => {
    const projection = projectPoolAtBaseCPR({
      ...basePool,
      remaining_term_months: 0,
    });
    expect(projection.rows).toEqual([]);
  });

  it("conserves principal each period (scheduled + prepay = bop - eop)", () => {
    const projection = projectPoolAtBaseCPR({ ...basePool, cpr_pct: 6 });
    for (let i = 0; i < projection.rows.length - 1; i++) {
      const row = projection.rows[i];
      const next = projection.rows[i + 1];
      const eop_implied = row.balance_bop - row.total_principal;
      // Allow tiny floating-point slack.
      expect(Math.abs(next.balance_bop - eop_implied)).toBeLessThan(0.01);
    }
  });

  it("does not produce negative cashflows under any realistic CPR", () => {
    for (const cpr of [0, 6, 12, 20, 50, 100]) {
      const projection = projectPoolAtBaseCPR({ ...basePool, cpr_pct: cpr });
      for (const row of projection.rows) {
        expect(row.interest_gross).toBeGreaterThanOrEqual(0);
        expect(row.scheduled_principal).toBeGreaterThanOrEqual(0);
        expect(row.prepay_principal).toBeGreaterThanOrEqual(0);
        expect(row.servicing).toBeGreaterThanOrEqual(0);
      }
    }
  });
});

describe("discountStream", () => {
  it("computes Macaulay duration of a single cashflow as t", () => {
    const result = discountStream([{ t: 24, cf: 100 }], 0.005);
    expect(result.mac_dur_months).toBeCloseTo(24, 6);
  });

  it("returns zero duration for an empty stream", () => {
    const result = discountStream([], 0.005);
    expect(result.mac_dur_months).toBe(0);
    expect(result.convexity_months_sq).toBe(0);
    expect(result.total_pv).toBe(0);
  });

  it("ignores zero cashflows", () => {
    const a = discountStream([{ t: 12, cf: 100 }, { t: 24, cf: 100 }], 0.005);
    const b = discountStream(
      [
        { t: 6, cf: 0 },
        { t: 12, cf: 100 },
        { t: 24, cf: 100 },
      ],
      0.005,
    );
    expect(a.mac_dur_months).toBeCloseTo(b.mac_dur_months, 6);
  });

  it("Macaulay duration is monotonically larger when cashflows are pushed later", () => {
    const early = discountStream(
      [
        { t: 6, cf: 50 },
        { t: 12, cf: 50 },
      ],
      0.005,
    );
    const late = discountStream(
      [
        { t: 24, cf: 50 },
        { t: 36, cf: 50 },
      ],
      0.005,
    );
    expect(late.mac_dur_months).toBeGreaterThan(early.mac_dur_months);
  });
});
