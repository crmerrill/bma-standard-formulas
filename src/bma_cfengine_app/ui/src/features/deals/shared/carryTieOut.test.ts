import { describe, expect, it } from "vitest";
import {
  computeStaticCarryTieOut,
  type BondInput,
  type CarryTieOutInputs,
} from "./carryTieOut";

const POOL_BAL = 100_000_000;

const basePool: CarryTieOutInputs["pool"] = {
  balance: POOL_BAL,
  wac_pct: 6.0,
  servicing_pct: 0.5,
  remaining_term_months: 360,
  cpr_pct: 6,
};

function bond(
  name: string,
  notional: number,
  coupon_pct: number,
  tranche_type = "SENIOR",
): BondInput {
  return { name, notional, coupon_pct, tranche_type };
}

describe("computeStaticCarryTieOut", () => {
  describe("degenerate cases", () => {
    it("flags is_degenerate when there are no bonds", () => {
      const result = computeStaticCarryTieOut({ pool: basePool, bonds: [] });
      expect(result.is_degenerate).toBe(true);
      expect(result.status).toBe("OK");
      expect(result.reason).toMatch(/Not enough structure/i);
    });

    it("flags is_degenerate when bonds eat the entire pool (no residual)", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", POOL_BAL, 5.0)],
      });
      expect(result.is_degenerate).toBe(true);
    });

    it("flags is_degenerate for zero-balance pools", () => {
      const result = computeStaticCarryTieOut({
        pool: { ...basePool, balance: 0 },
        bonds: [bond("A", 1, 5)],
      });
      expect(result.is_degenerate).toBe(true);
    });
  });

  describe("classification bands (default thresholds: OK 5%-35%)", () => {
    it("classifies a typical structure with reasonable residual yield as OK", () => {
      // 5.5% net pool yield. Bonds: A(85%, 5.0%), B(10%, 6.0%). Residual: 5%.
      // Notional carry: pool yields ~5.5M; bonds cost = 4.25M+0.6M = 4.85M.
      // Residual = 0.65M / 5M = 13% (~OK band).
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 85_000_000, 5.0), bond("B", 10_000_000, 6.0)],
      });
      expect(result.status).toBe("OK");
      expect(
        result.implied_residual_yield_convexity_adjusted_pct,
      ).toBeGreaterThan(5);
      expect(
        result.implied_residual_yield_convexity_adjusted_pct,
      ).toBeLessThan(35);
    });

    it("BLOCKS when bonds are over-couponed (negative implied yield)", () => {
      // Pool nets ~5.5%. If we issue 95% bonds at 7% (cost > pool yield),
      // residual yield must be negative.
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 95_000_000, 7.0)],
      });
      expect(result.status).toBe("BLOCK");
      expect(result.reason).toMatch(/over-couponed|negative/i);
      expect(
        result.implied_residual_yield_convexity_adjusted_pct,
      ).toBeLessThan(0);
    });

    it("BLOCKS when bonds are wildly under-coupon (>50% implied residual)", () => {
      // 5.5% net pool, residual gets it almost all -- bonds at 0.5%, 95%.
      // Implied residual blows past 50%.
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 95_000_000, 0.5)],
      });
      expect(result.status).toBe("BLOCK");
      expect(
        result.implied_residual_yield_convexity_adjusted_pct,
      ).toBeGreaterThan(50);
    });

    it("WARNs when residual yield is in the 35%-50% band", () => {
      // 85M @ 4% senior + 10M @ 4.5% mezz on a 5.5% net pool lands the
      // convexity-adjusted implied yield around 42% -- inside the upper
      // warn band (35%-50%) per the locked default thresholds.
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 85_000_000, 4.0), bond("B", 10_000_000, 4.5)],
      });
      expect(result.status).toBe("WARN");
      const y = result.implied_residual_yield_convexity_adjusted_pct;
      expect(y).toBeGreaterThan(35);
      expect(y).toBeLessThanOrEqual(50);
    });

    it("WARNs when implied residual yield is just below 5%", () => {
      // 95% @ 5.7%: bond cost 5.415M on pool income 5.5M => barely
      // positive notional (1.7%) which the static engine compresses
      // further with duration weighting => low single-digit % -> WARN.
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 95_000_000, 5.7)],
      });
      expect(result.status).toBe("WARN");
      const y = result.implied_residual_yield_convexity_adjusted_pct;
      expect(y).toBeGreaterThanOrEqual(0);
      expect(y).toBeLessThan(5);
    });
  });

  describe("output shape and economics", () => {
    it("computes residual_balance as pool - bonds total", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 80_000_000, 5), bond("B", 10_000_000, 6)],
      });
      expect(result.residual_balance).toBeCloseTo(10_000_000, 0);
    });

    it("excludes RESIDUAL and PSEUDO tranches from the bond stack", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [
          bond("A", 90_000_000, 5),
          bond("R", 0, 0, "RESIDUAL"),
          bond("svc_fee", 1_000_000, 5, "PSEUDO"),
        ],
      });
      expect(result.tranches.length).toBe(1);
      expect(result.tranches[0].name).toBe("A");
      expect(result.bonds_total_notional).toBe(90_000_000);
    });

    it("tranche durations are positive and shorter than pool duration", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 80_000_000, 5), bond("B", 10_000_000, 6)],
      });
      for (const t of result.tranches) {
        expect(t.duration_years).toBeGreaterThan(0);
      }
      const senior = result.tranches[0];
      // Senior in a sequential pay receives principal first => shorter
      // than the pool duration.
      expect(senior.duration_years).toBeLessThan(result.pool_duration_years);
    });

    it("notional and duration measures of implied yield are both finite", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 80_000_000, 5), bond("B", 10_000_000, 6)],
      });
      expect(
        Number.isFinite(result.implied_residual_yield_notional_pct),
      ).toBe(true);
      expect(
        Number.isFinite(result.implied_residual_yield_duration_pct),
      ).toBe(true);
      expect(
        Number.isFinite(result.implied_residual_yield_convexity_adjusted_pct),
      ).toBe(true);
    });

    it("convexity adjustment shifts implied yield by less than the duration measure", () => {
      const result = computeStaticCarryTieOut({
        pool: basePool,
        bonds: [bond("A", 80_000_000, 5), bond("B", 10_000_000, 6)],
      });
      const dur = result.implied_residual_yield_duration_pct;
      const cvx = result.implied_residual_yield_convexity_adjusted_pct;
      // Convexity adjustment should be a small (~< 1pp) shift relative
      // to the duration-only number for typical deals.
      expect(Math.abs(cvx - dur)).toBeLessThan(2);
    });
  });

  describe("threshold overrides", () => {
    it("respects user-supplied OK band", () => {
      // The default deal lands ~9% implied yield (in the default
      // 5%-35% OK band). Pushing the floor to 25% flips it to WARN
      // because the same yield is now under the user's OK floor.
      const inputs: CarryTieOutInputs = {
        pool: basePool,
        bonds: [bond("A", 85_000_000, 5.0), bond("B", 10_000_000, 6.0)],
      };
      const default_ = computeStaticCarryTieOut(inputs);
      const tight = computeStaticCarryTieOut({
        ...inputs,
        threshold_overrides: { ok_band_low_pct: 25 },
      });
      expect(default_.status).toBe("OK");
      const y = default_.implied_residual_yield_convexity_adjusted_pct;
      expect(y).toBeGreaterThan(5);
      expect(y).toBeLessThan(25);
      expect(tight.status).toBe("WARN");
    });
  });
});
