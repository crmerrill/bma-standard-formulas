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
  const lo = bond.schedule_speed_low;
  const hi = bond.schedule_speed_high;
  let tgtRaw: unknown = bond.tac_pricing_psa;
  if (typeof lo === "number" && typeof hi === "number") {
    if (Math.abs(lo - hi) > 1e-9) return null;
    tgtRaw = lo;
  }
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

// ---------------------------------------------------------------------------
// OA1: Opaque IR field passthrough
// ---------------------------------------------------------------------------
//
// Fields that the Blockly workspace cannot generate (Phase 6/7/8/9 additions,
// CalculationNode arrays, deal_knobs, etc.) must be preserved when the user
// saves a deal after making Blockly edits. This utility extracts them from the
// current saved IR and merges them back into a freshly generated IR.
//
// "Opaque" means: not produced by generateDealIR, not in any Blockly field or
// block.data, and not already handled by the schedule overlay merge path.
// ---------------------------------------------------------------------------

/**
 * Per-bond opaque fields that Blockly cannot generate.
 * Matched by bond name when merging back into generated IR.
 */
const OPAQUE_BOND_FIELDS = [
  "nla_starting_balance",
  "required_subordination_pct",
  "seniority",
] as const;

/**
 * Per-account opaque fields (Phase 7 minimum_schedule, etc.).
 */
const OPAQUE_ACCOUNT_FIELDS = [
  "minimum_schedule",
] as const;

/**
 * Per-trigger opaque fields (Phase 9 window_periods, comparison).
 */
const OPAQUE_TRIGGER_FIELDS = [
  "window_periods",
  "comparison",
] as const;

/**
 * Top-level DealDefinition opaque fields.
 */
const OPAQUE_TOP_LEVEL_FIELDS = [
  "calculations",
  "deal_state_trigger",
  "initial_deal_state",
  "series_id",
  "deal_knobs",
] as const;

export interface OpaqueIrFields {
  topLevel: Record<string, unknown>;
  /** keyed by bond name */
  bondFields: Record<string, Record<string, unknown>>;
  /** keyed by account name */
  accountFields: Record<string, Record<string, unknown>>;
  /** keyed by trigger name */
  triggerFields: Record<string, Record<string, unknown>>;
}

/**
 * Extract opaque IR fields from a saved IR JSON so they can be preserved
 * when the Blockly workspace regenerates the IR.
 */
export function extractOpaqueIrFields(irJson: string): OpaqueIrFields {
  const result: OpaqueIrFields = {
    topLevel: {},
    bondFields: {},
    accountFields: {},
    triggerFields: {},
  };
  let ir: unknown;
  try { ir = JSON.parse(irJson); } catch { return result; }
  if (!ir || typeof ir !== "object") return result;
  const root = ir as Record<string, unknown>;

  // Top-level opaque fields
  for (const key of OPAQUE_TOP_LEVEL_FIELDS) {
    if (root[key] !== undefined && root[key] !== null) {
      result.topLevel[key] = root[key];
    }
  }

  // Per-bond opaque fields
  const bonds = root.bonds;
  if (Array.isArray(bonds)) {
    for (const b of bonds) {
      if (!b || typeof b !== "object") continue;
      const bond = b as Record<string, unknown>;
      const name = String(bond.name ?? "");
      if (!name) continue;
      const extracted: Record<string, unknown> = {};
      for (const key of OPAQUE_BOND_FIELDS) {
        if (bond[key] !== undefined && bond[key] !== null) {
          extracted[key] = bond[key];
        }
      }
      if (Object.keys(extracted).length > 0) result.bondFields[name] = extracted;
    }
  }

  // Per-account opaque fields
  const accounts = root.accounts;
  if (Array.isArray(accounts)) {
    for (const a of accounts) {
      if (!a || typeof a !== "object") continue;
      const acct = a as Record<string, unknown>;
      const name = String(acct.name ?? "");
      if (!name) continue;
      const extracted: Record<string, unknown> = {};
      for (const key of OPAQUE_ACCOUNT_FIELDS) {
        if (acct[key] !== undefined && acct[key] !== null) {
          extracted[key] = acct[key];
        }
      }
      if (Object.keys(extracted).length > 0) result.accountFields[name] = extracted;
    }
  }

  // Per-trigger opaque fields
  const triggers = root.triggers;
  if (Array.isArray(triggers)) {
    for (const t of triggers) {
      if (!t || typeof t !== "object") continue;
      const trig = t as Record<string, unknown>;
      const name = String(trig.name ?? "");
      if (!name) continue;
      const extracted: Record<string, unknown> = {};
      for (const key of OPAQUE_TRIGGER_FIELDS) {
        if (trig[key] !== undefined && trig[key] !== null) {
          extracted[key] = trig[key];
        }
      }
      if (Object.keys(extracted).length > 0) result.triggerFields[name] = extracted;
    }
  }

  return result;
}

/**
 * Merge opaque IR fields back into a freshly generated IR.
 * Generated IR fields are NOT overwritten — opaque fields only fill in gaps.
 */
export function mergeOpaqueIrFields(ir: unknown, opaque: OpaqueIrFields): unknown {
  if (!ir || typeof ir !== "object") return ir;
  const root = { ...(ir as Record<string, unknown>) };

  // Merge top-level fields (do not overwrite what generateDealIR produces)
  for (const [key, value] of Object.entries(opaque.topLevel)) {
    // deal_knobs: deep-merge so Blockly-generated entries win over saved ones.
    if (key === "deal_knobs") {
      const existing = typeof root[key] === "object" && root[key] !== null
        ? (root[key] as Record<string, unknown>)
        : {};
      root[key] = { ...(value as Record<string, unknown>), ...existing };
    } else if (root[key] === undefined || root[key] === null || root[key] === "") {
      root[key] = value;
    }
  }

  // Merge per-bond opaque fields
  if (Array.isArray(root.bonds)) {
    root.bonds = root.bonds.map((b) => {
      if (!b || typeof b !== "object") return b;
      const bond = b as Record<string, unknown>;
      const name = String(bond.name ?? "");
      const extras = opaque.bondFields[name];
      if (!extras) return bond;
      // Only inject fields missing from the generated bond
      const patch: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(extras)) {
        if (bond[k] === undefined || bond[k] === null) patch[k] = v;
      }
      return Object.keys(patch).length > 0 ? { ...bond, ...patch } : bond;
    });
  }

  // Merge per-account opaque fields
  if (Array.isArray(root.accounts)) {
    root.accounts = root.accounts.map((a) => {
      if (!a || typeof a !== "object") return a;
      const acct = a as Record<string, unknown>;
      const name = String(acct.name ?? "");
      const extras = opaque.accountFields[name];
      if (!extras) return acct;
      const patch: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(extras)) {
        if (acct[k] === undefined || acct[k] === null) patch[k] = v;
      }
      return Object.keys(patch).length > 0 ? { ...acct, ...patch } : acct;
    });
  }

  // Merge per-trigger opaque fields
  if (Array.isArray(root.triggers)) {
    root.triggers = root.triggers.map((t) => {
      if (!t || typeof t !== "object") return t;
      const trig = t as Record<string, unknown>;
      const name = String(trig.name ?? "");
      const extras = opaque.triggerFields[name];
      if (!extras) return trig;
      const patch: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(extras)) {
        if (trig[k] === undefined || trig[k] === null) patch[k] = v;
      }
      return Object.keys(patch).length > 0 ? { ...trig, ...patch } : trig;
    });
  }

  return root;
}

/**
 * Extract an initial ScheduleOverlay from a loaded IR by seeding any PAC/TAC bond
 * that already has schedule_contract + schedule_derivation entries. This prevents
 * schedules from being discarded when a deal with existing derivations is loaded
 * into the editor before the user triggers a re-derive.
 */
export function extractScheduleOverlayFromIr(irJson: string): ScheduleOverlay {
  const overlay: ScheduleOverlay = {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(irJson) as unknown;
  } catch {
    return overlay;
  }
  if (!parsed || typeof parsed !== "object") return overlay;
  const bonds = (parsed as Record<string, unknown>).bonds;
  if (!Array.isArray(bonds)) return overlay;
  for (const b of bonds) {
    if (!b || typeof b !== "object") continue;
    const bond = b as Record<string, unknown>;
    const kind = bond.kind;
    if (kind !== "PAC" && kind !== "TAC") continue;
    const name = String(bond.name ?? "");
    if (!name) continue;
    const contract = bond.schedule_contract;
    if (!Array.isArray(contract) || contract.length === 0) continue;
    // Only seed from machine-derived PSA schedules: those have a non-empty
    // schedule_derivation with an `inputs` block (written by build_psa_schedule_overlay).
    // Authored schedules (CUSTOM_VECTOR, CPR, user-edited) must not be frozen
    // into the overlay as they may be intentionally different from PSA derivation.
    const derivation = bond.schedule_derivation as Record<string, unknown> | undefined;
    const hasPsaDerivation =
      derivation &&
      typeof derivation === "object" &&
      derivation.inputs !== undefined;
    if (!hasPsaDerivation) continue;
    overlay[name] = {
      schedule_contract: contract as Array<Record<string, unknown>>,
      schedule_derivation: derivation as Record<string, unknown>,
    };
  }
  return overlay;
}

/**
 * Whether merged IR has at least one PSA-mode PAC/TAC bond whose schedule_derivation
 * inputs no longer match pool + bond speeds / sizing (Phase 1i stale indicator).
 * Also detects staleness when the support stack (SUPPORTED_BY relations) changes.
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
    // Accept PAC/TAC bonds with any schedule model or with speed values set
    // (schedule_model_type may be absent after round-trip).
    const kind = bond.kind;
    if (kind !== "PAC" && kind !== "TAC") continue;
    if (bond.schedule_model_type && bond.schedule_model_type !== "PSA") continue;

    const deriv = bond.schedule_derivation as Record<string, unknown> | undefined;
    const storedInputs = deriv?.inputs as Record<string, unknown> | undefined;

    if (kind === "PAC") {
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

    // Check support-stack fingerprint: if SUPPORTED_BY targets changed since
    // the schedule was derived, the derivation result may be wrong.
    const currentSupportNames = (
      (bond.relations as Array<Record<string, unknown>> | undefined) ?? []
    )
      .filter((r) => r.relation_type === "SUPPORTED_BY")
      .flatMap((r) => (Array.isArray(r.targets) ? r.targets.map(String) : []))
      .sort()
      .join(",");
    const storedSupportNames = String(storedInputs?.support_names ?? "");
    if (
      storedInputs !== undefined
      && currentSupportNames !== storedSupportNames
    ) {
      return {
        stale: true,
        reason: "Support tranche stack changed since last PSA schedule derivation.",
      };
    }
  }
  return { stale: false, reason: "" };
}
