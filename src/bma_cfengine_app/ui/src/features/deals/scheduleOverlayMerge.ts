/**
 * Phase 1i: merge PSA-derived schedule_contract + schedule_derivation into
 * Blockly-generated IR without mutating workspace blocks.
 */

export type ScheduleOverlayEntry = {
  schedule_contract: Array<Record<string, unknown>>;
  schedule_derivation: Record<string, unknown>;
};

export type ScheduleOverlay = Record<string, ScheduleOverlayEntry>;

export function mergeScheduleOverlay(ir: unknown, overlay: ScheduleOverlay | null): unknown {
  if (!overlay || Object.keys(overlay).length === 0) return ir;
  if (!ir || typeof ir !== "object") return ir;
  const root = ir as Record<string, unknown>;
  const bonds = root.bonds;
  if (!Array.isArray(bonds)) return ir;
  const nextBonds = bonds.map((b) => {
    if (!b || typeof b !== "object") return b;
    const bond = b as Record<string, unknown>;
    const name = String(bond.name ?? "");
    const patch = overlay[name];
    if (!patch) return bond;
    return {
      ...bond,
      schedule_contract: patch.schedule_contract,
      schedule_derivation: patch.schedule_derivation,
    };
  });
  return { ...root, bonds: nextBonds };
}

type PoolDerivationCtx = {
  balance: number;
  wac_pct: number;
  term_months: number;
  horizon_months: number;
};

function _faceUsd(bond: Record<string, unknown>, poolBalance: number): number {
  const sz = bond.notional;
  if (typeof sz === "number" && sz > 0) return sz;
  const pct = bond.notional_pct_of_collateral;
  if (typeof pct === "number" && pct > 0 && poolBalance > 0) return (pct / 100) * poolBalance;
  return 0;
}

function _expectedPacInputs(
  bond: Record<string, unknown>,
  pool: PoolDerivationCtx,
): Record<string, unknown> | null {
  const loRaw = bond.schedule_speed_low ?? bond.pac_lower_psa;
  const hiRaw = bond.schedule_speed_high ?? bond.pac_upper_psa;
  if (typeof loRaw !== "number" || typeof hiRaw !== "number") return null;
  const psaLo = Math.min(loRaw, hiRaw);
  const psaHi = Math.max(loRaw, hiRaw);
  const face = _faceUsd(bond, pool.balance);
  if (face <= 0) return null;
  return {
    bond: String(bond.name ?? ""),
    pool_balance: pool.balance,
    pool_wac_pct: pool.wac_pct,
    pool_term_months: pool.term_months,
    horizon_months: pool.horizon_months,
    psa_low: psaLo,
    psa_high: psaHi,
    tranche_face: face,
  };
}

function _expectedTacInputs(
  bond: Record<string, unknown>,
  pool: PoolDerivationCtx,
): Record<string, unknown> | null {
  const tgtRaw = bond.schedule_speed_target ?? bond.tac_pricing_psa;
  if (typeof tgtRaw !== "number") return null;
  const face = _faceUsd(bond, pool.balance);
  if (face <= 0) return null;
  return {
    bond: String(bond.name ?? ""),
    pool_balance: pool.balance,
    pool_wac_pct: pool.wac_pct,
    pool_term_months: pool.term_months,
    horizon_months: pool.horizon_months,
    psa_target: tgtRaw,
    tranche_face: face,
  };
}

function _inputsMatch(
  expected: Record<string, unknown>,
  stored: Record<string, unknown> | undefined,
): boolean {
  if (!stored) return false;
  for (const k of Object.keys(expected)) {
    const ev = expected[k];
    const sv = stored[k];
    if (k === "bond") {
      if (ev !== sv) return false;
      continue;
    }
    if (typeof ev === "number" && typeof sv === "number") {
      const intKeys = new Set(["horizon_months", "pool_term_months"]);
      const tol = intKeys.has(k) ? 0 : 1e-2;
      if (tol === 0) {
        if (Math.round(ev) !== Math.round(sv)) return false;
      } else if (Math.abs(ev - sv) > tol) return false;
    } else if (ev !== sv) {
      return false;
    }
  }
  return true;
}

/**
 * Whether merged IR has at least one PSA-mode PAC/TAC bond whose schedule_derivation
 * inputs no longer match pool + bond speeds / sizing (Phase 1i stale indicator).
 */
export function computePsaScheduleStale(
  irJson: string,
  pool: PoolDerivationCtx | null,
): { stale: boolean; reason: string } {
  if (!pool || pool.balance <= 0 || pool.wac_pct <= 0 || pool.term_months <= 0 || pool.horizon_months <= 0) {
    return { stale: false, reason: "" };
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(irJson) as unknown;
  } catch {
    return { stale: false, reason: "" };
  }
  if (!parsed || typeof parsed !== "object") return { stale: false, reason: "" };
  const bonds = (parsed as Record<string, unknown>).bonds;
  if (!Array.isArray(bonds)) return { stale: false, reason: "" };

  for (const b of bonds) {
    if (!b || typeof b !== "object") continue;
    const bond = b as Record<string, unknown>;
    if (bond.schedule_model_type !== "PSA") continue;
    const behavior = bond.tranche_behavior;
    if (behavior !== "PAC" && behavior !== "TAC") continue;

    const deriv = bond.schedule_derivation as Record<string, unknown> | undefined;
    const storedInputs = deriv?.inputs as Record<string, unknown> | undefined;

    if (behavior === "PAC") {
      const exp = _expectedPacInputs(bond, pool);
      if (!exp) continue;
      if (!_inputsMatch(exp, storedInputs))
        return { stale: true, reason: "PAC PSA schedule does not match current pool or speed band." };
    } else {
      const exp = _expectedTacInputs(bond, pool);
      if (!exp) continue;
      if (!_inputsMatch(exp, storedInputs))
        return { stale: true, reason: "TAC PSA schedule does not match current pool or pricing speed." };
    }
  }
  return { stale: false, reason: "" };
}
