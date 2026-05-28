/**
 * Blockly workspace -> DealDefinition IR generator.
 *
 * Scans all top-level waterfall blocks on the workspace (no Deal root needed).
 * Extracts bond/account definitions from target pieces inside pay rules.
 */

interface BondDefIR {
  name: string;
  kind: "CASH_PAY" | "PAC" | "TAC" | "IO" | "PO" | "Z" | "RESIDUAL" | "PSEUDO";
  group_id?: string | null;
  coupon: number;
  notional_pct_of_collateral: number;
  notional: number;
  is_bond: boolean;
  is_pseudo: boolean;
  coupon_type: string;
  index_name: string | null;
  margin: number | null;
  pay_mode: "CASH_PAY" | "PIK";
  schedule_model_type: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR" | null;
  schedule_priority_tier: number | null;
  schedule_depends_on: string | null;
  schedule_speed_low: number | null;
  schedule_speed_high: number | null;
  schedule_custom_vector: string | null;
  schedule_contract: Array<{ period: number; target_principal: number }>;
  schedule_tolerance_bps: number | null;
  relations: Array<{ relation_type: string; targets: string[] }>;
  z_accrual_enabled: boolean;
  z_release_trigger: string | null;
}

interface AccountDefIR {
  name: string;
  account_category: string;
  starting_amount: number;
  starting_pct: number | null;
  starting_basis: string;
}

interface FeeDefIR {
  name: string;
  basis_type: string;
  amount: number;
  /** Percent rate when basis_type is COLLATERAL_BALANCE; otherwise null */
  rate: number | null;
  frequency: string;
}

interface TriggerNodeIR {
  name: string;
  metric_type: string;
  threshold_value: number;
}

interface RuleNodeIR {
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
  bonds: BondDefIR[];
  accounts: AccountDefIR[];
  fees: FeeDefIR[];
  triggers: TriggerNodeIR[];
  waterfall_rules: RuleNodeIR[];
  collateral_groups: CollateralGroupDefIR[];
  deal_knobs: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function walkChain(start: any): any[] {
  const blocks: any[] = [];
  let cur = start;
  while (cur) {
    blocks.push(cur);
    cur = cur.getNextBlock();
  }
  return blocks;
}

function getStatementChain(parent: any, name: string): any[] {
  const first = parent.getInputTargetBlock(name);
  return first ? walkChain(first) : [];
}

const PAY_TYPE_MAP: Record<string, string> = {
  INTEREST: "PAY_INTEREST",
  INTEREST_SHORTFALL: "PAY_INTEREST_SHORTFALL",
  PRINCIPAL: "PAY_PRINCIPAL",
  PRIORITY_PRINCIPAL: "PAY_PRINCIPAL",
  WRITEDOWN: "PAY_WRITEDOWN",
  LOSS_RECOVERY: "PAY_PRINCIPAL",
  REMAINING: "PAY_RESIDUAL",
};

const FEE_BASIS_MAP: Record<string, string> = {
  PCT_POOL: "COLLATERAL_BALANCE",
  FIXED_DOLLAR: "FIXED_DOLLAR",
  PER_LOAN: "PER_LOAN",
};

const TRIGGER_METRIC_MAP: Record<string, string> = {
  CUM_LOSS: "CUMULATIVE_LOSS",
  CUM_DEFAULT: "CUMULATIVE_DEFAULT",
  DELINQUENCY: "DELINQUENCY_RATE",
  OC_RATIO: "OC_TEST",
  IC_RATIO: "IC_TEST",
  CUSTOM: "CUSTOM",
};

const RULE_SOURCE_MAP: Record<string, string> = {
  COLLECTION: "CASH",
  // Legacy UI source dropdown values that mapped to interest / principal streams.
  // Preserve the split-stream semantics: INT_COLLECTION -> ACT_INT, not CASH.
  PRIN_COLLECTION: "ACT_PRIN",
  INT_COLLECTION:  "ACT_INT",
  // Old token aliases kept for backward compat; all collapse to CASH.
  DISTRIBUTION: "CASH",
  RESERVE: "CASH",
  PREFUNDING: "CASH",
  CAP_INTEREST: "CASH",
  EXPENSE: "CASH",
  REINVESTMENT: "CASH",
  SWAP_HEDGE: "CASH",
  ESCROW: "CASH",
  YIELD_SUPPLEMENT: "CASH",
  COLLATERAL: "CASH",
  CASH: "CASH",
  // Current canonical tokens pass through unchanged.
  ACT_INT:  "ACT_INT",
  ACT_PRIN: "ACT_PRIN",
  LOSS:     "LOSS",
};

function normalizeRuleSource(source: string | null | undefined): string {
  const token = source || "COLLECTION";
  // If the token is in the map, use the mapped value.
  // If not, pass the token through unchanged so that account/bond names
  // used as coverage-mode sources are not silently collapsed to CASH.
  if (Object.prototype.hasOwnProperty.call(RULE_SOURCE_MAP, token)) {
    return RULE_SOURCE_MAP[token];
  }
  return token;
}

// ---------------------------------------------------------------------------
// Target extraction (bonds + accounts from inside pay rules)
// ---------------------------------------------------------------------------

interface TargetInfo {
  name: string;
  isBond: boolean;
  bondType?: string;
  faceAmt?: number;
  sizePctPool?: number;
  coupon?: number;
  indexName?: string;
  margin?: number | null;
  accrual?: string;
  payMode?: "CASH_PAY" | "PIK";
  kind?: "CASH_PAY" | "PAC" | "TAC" | "IO" | "PO" | "Z" | "RESIDUAL" | "PSEUDO";
  groupId?: string | null;
  scheduleModelType?: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
  schedulePriorityTier?: number | null;
  scheduleDependsOn?: string | null;
  scheduleSpeedLow?: number | null;
  scheduleSpeedHigh?: number | null;
  scheduleCustomVector?: string | null;
  scheduleContract?: Array<{ period: number; target_principal: number }>;
  scheduleToleranceBps?: number | null;
  supportTranches?: string[];
  relations?: Array<{ relation_type: string; targets: string[] }>;
  zReleaseTrigger?: string | null;
  zAccrualEnabled?: boolean;
  accountType?: string;
  /** PCT_STACK = % of total bond face; FIXED_DOLLAR = $ */
  initialMode?: string;
  initialAmt?: number;
}

function extractTargets(ruleBlock: any, inputName = "TARGETS"): TargetInfo[] {
  const targets: TargetInfo[] = [];
  for (const t of getStatementChain(ruleBlock, inputName)) {
    if (t.type === "bond_target") {
      // Parse the full block.data payload stashed by irToBlocklyState._bondDataPayload.
      // This recovers all IR fields that have no native Blockly field: kind, group_id,
      // schedule_contract, relations, z_accrual_enabled, coupon_type.
      let kindFromData: string | undefined;
      let groupIdFromData: string | null | undefined;
      let couponTypeFromData: string | undefined;
      let relationData: Array<{ relation_type: string; targets: string[] }> = [];
      let scheduleContractFromData: Array<{ period: number; target_principal: number }> = [];
      let zAccrualEnabledFromData: boolean | undefined;
      if (typeof t.data === "string" && t.data.trim()) {
        try {
          const parsed = JSON.parse(t.data) as Record<string, unknown>;
          if (typeof parsed.kind === "string" && parsed.kind) {
            kindFromData = parsed.kind;
          }
          if (typeof parsed.group_id === "string") {
            groupIdFromData = parsed.group_id || null;
          }
          if (typeof parsed.coupon_type === "string" && parsed.coupon_type) {
            couponTypeFromData = parsed.coupon_type;
          }
          if (Array.isArray(parsed.relations)) {
            // Preserve the full relation payload including weights, leverage,
            // cap, floor, description so the backend schema is not truncated.
            relationData = parsed.relations
              .filter((r) => typeof r === "object" && r !== null)
              .map((r) => {
                const rel = r as Record<string, unknown>;
                const entry: Record<string, unknown> = {
                  relation_type: String(rel.relation_type || "").toUpperCase(),
                  targets: Array.isArray(rel.targets) ? rel.targets.map((x) => String(x)) : [],
                };
                if (Array.isArray(rel.weights)) entry.weights = rel.weights.map(Number);
                if (typeof rel.leverage === "number") entry.leverage = rel.leverage;
                if (typeof rel.cap === "number") entry.cap = rel.cap;
                if (typeof rel.floor === "number") entry.floor = rel.floor;
                if (typeof rel.description === "string") entry.description = rel.description;
                return entry as { relation_type: string; targets: string[] };
              })
              .filter((r) => r.relation_type.length > 0 && r.targets.length > 0);
          }
          if (Array.isArray(parsed.schedule_contract)) {
            // Preserve both target_principal and target_balance entries so
            // planned-balance schedules (target_balance) are not corrupted.
            scheduleContractFromData = (parsed.schedule_contract as Array<Record<string, unknown>>)
              .filter((e) => typeof e === "object" && e !== null)
              .map((e) => {
                const entry: Record<string, unknown> = { period: Number(e.period ?? 0) };
                if ("target_balance" in e) {
                  entry.target_balance = Number(e.target_balance);
                } else {
                  entry.target_principal = Number(e.target_principal ?? 0);
                }
                return entry as { period: number; target_principal: number };
              });
          }
          // Read z_accrual_enabled as explicit boolean (including false).
          if (typeof parsed.z_accrual_enabled === "boolean") {
            zAccrualEnabledFromData = parsed.z_accrual_enabled;
          }
        } catch {
          // Ignore malformed block.data; fall back to visible fields.
        }
      }
      // coupon_type from block.data overrides the visible BOND_TYPE dropdown so
      // PO (ZERO) and IO classes survive round-trip even when the dropdown shows FIXED.
      const bondTypeFromField = t.getFieldValue("BOND_TYPE") || "FIXED";
      const bondType = couponTypeFromData || bondTypeFromField;
      const payMode = (t.getFieldValue("PAY_MODE") || "CASH_PAY") as "CASH_PAY" | "PIK";
      targets.push({
        name: t.getFieldValue("NAME") || "X",
        isBond: true,
        bondType,
        payMode,
        faceAmt: t.getFieldValue("FACE_AMT") || 0,
        sizePctPool: Number(t.getFieldValue("SIZE_PCT_POOL") || 0),
        coupon: t.getFieldValue("COUPON") || 0,
        indexName: bondType === "FLOATING" ? (t.getFieldValue("INDEX_NAME") || null) : null,
        margin: bondType === "FLOATING" ? Number(t.getFieldValue("MARGIN") || 0) : null,
        accrual: t.getFieldValue("ACCRUAL") || "30_360",
        kind: kindFromData as TargetInfo["kind"],
        groupId: groupIdFromData,
        scheduleContract: scheduleContractFromData.length > 0 ? scheduleContractFromData : [],
        scheduleToleranceBps: null,
        supportTranches: [],
        relations: relationData,
        zReleaseTrigger: null,
        zAccrualEnabled: zAccrualEnabledFromData,
      });
    } else if (t.type === "residual_target") {
      targets.push({
        name: t.getFieldValue("NAME") || "R",
        isBond: false,
      });
    } else if (t.type === "account_target") {
      const mode = t.getFieldValue("INITIAL_MODE") || "PCT_STACK";
      const amt =
        t.getFieldValue("INITIAL_AMT") ??
        t.getFieldValue("INITIAL_PCT") ??
        0;
      targets.push({
        name: t.getFieldValue("ACCOUNT_TYPE") || "RESERVE",
        isBond: false,
        accountType: t.getFieldValue("ACCOUNT_TYPE") || "RESERVE",
        initialMode: mode,
        initialAmt: Number(amt) || 0,
      });
    }
  }
  return targets;
}

/** Parse the rule-level block.data payload stashed by irToBlocklyState. */
function extractRuleBlockData(block: any): {
  ruleId?: string;
  groupId?: string | null;
  capMode?: string | null;
  coverageMode?: string | null;
  targetWeights?: number[] | null;
  extraTargets?: string[];
} {
  if (typeof block.data !== "string" || !block.data.trim()) return {};
  try {
    const parsed = JSON.parse(block.data) as Record<string, unknown>;
    return {
      ruleId:        typeof parsed.rule_id === "string" ? parsed.rule_id : undefined,
      groupId:       typeof parsed.group_id === "string" ? parsed.group_id : null,
      capMode:       typeof parsed.cap_mode === "string" ? parsed.cap_mode : null,
      coverageMode:  typeof parsed.coverage_mode === "string" ? parsed.coverage_mode : null,
      targetWeights: Array.isArray(parsed.target_weights) ? parsed.target_weights.map(Number) : null,
      extraTargets:  Array.isArray(parsed.extra_targets) ? parsed.extra_targets.map(String) : [],
    };
  } catch {
    return {};
  }
}

function extractSupportBondNames(ruleBlock: any): string[] {
  const names = extractTargets(ruleBlock, "SUPPORT_BONDS")
    .filter((target) => target.isBond)
    .map((target) => target.name)
    .filter(Boolean);
  return Array.from(new Set(names));
}

// ---------------------------------------------------------------------------
// Waterfall walk (recursive for triggers)
// ---------------------------------------------------------------------------

interface Ctx {
  order: number;
  rules: RuleNodeIR[];
  fees: FeeDefIR[];
  triggers: TriggerNodeIR[];
  bonds: Map<string, TargetInfo>;
  accounts: Map<string, TargetInfo>;
  activeTrigger: string | null;
  /** false = THEN (run when trigger active); true = ELSE (run when not active) */
  conditionInvert: boolean;
}

function emitSplitCash(block: any, ctx: Ctx): void {
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const out1 = String(block.getFieldValue("OUT_1") || "").trim();
  const out2 = String(block.getFieldValue("OUT_2") || "").trim();
  const { ruleId, groupId, targetWeights, extraTargets } = extractRuleBlockData(block);

  const targets: string[] = [];
  if (out1) targets.push(out1);
  if (out2) targets.push(out2);
  if (extraTargets) targets.push(...extraTargets);

  if (targets.length === 0) return;

  ctx.rules.push({
    rule_id: ruleId || `split_${ctx.order}`,
    rule_type: "SPLIT_CASH",
    order: ctx.order,
    from_sources: [source],
    to_targets: targets,
    payment_style: "SEQUENTIAL",
    max_amount_fixed: null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
    group_id: groupId,
    // Restore target_weights from block.data; fall back to equal split.
    ...(targetWeights && targetWeights.length === targets.length
      ? { target_weights: targetWeights }
      : {}),
  });
  ctx.order++;
}

function walkWaterfall(blocks: any[], ctx: Ctx): void {
  for (const b of blocks) {
    switch (b.type) {
      case "pay_sequential": emitSequential(b, ctx); break;
      case "pay_pro_rata": emitProRata(b, ctx); break;
      case "pay_pac_schedule": emitPacTacSchedule(b, ctx, "PAC"); break;
      case "pay_tac_schedule": emitPacTacSchedule(b, ctx, "TAC"); break;
      case "pay_accretion_redirect": emitAccretionRedirect(b, ctx); break;
      case "pay_fee": emitFee(b, ctx); break;
      case "trigger_wrapper": emitTrigger(b, ctx); break;
      case "split_account": emitSplitCash(b, ctx); break;
    }
  }
}

function registerTargets(targets: TargetInfo[], ctx: Ctx): void {
  for (const t of targets) {
    if (t.isBond) {
      const existing = ctx.bonds.get(t.name);
      if (!existing) {
        ctx.bonds.set(t.name, t);
        continue;
      }
      // Merge semantics: prefer the first non-empty / non-null value for
      // economic fields so the data stashed by irToBlocklyState on the
      // FIRST occurrence of a bond target is not overwritten by a second
      // (potentially empty) occurrence of the same bond name in a later rule.
      ctx.bonds.set(t.name, {
        ...existing,
        ...t,
        // Economic fields: keep non-empty value; fall back to whichever is non-empty.
        kind:
          (existing.kind && existing.kind !== "CASH_PAY") ? existing.kind
          : (t.kind && t.kind !== "CASH_PAY") ? t.kind
          : existing.kind || t.kind,
        groupId:
          existing.groupId != null ? existing.groupId : t.groupId,
        scheduleContract:
          (existing.scheduleContract && existing.scheduleContract.length > 0)
            ? existing.scheduleContract
            : (t.scheduleContract && t.scheduleContract.length > 0)
              ? t.scheduleContract
              : existing.scheduleContract,
        scheduleToleranceBps:
          existing.scheduleToleranceBps != null ? existing.scheduleToleranceBps
          : t.scheduleToleranceBps,
        supportTranches:
          (existing.supportTranches && existing.supportTranches.length > 0)
            ? existing.supportTranches
            : (t.supportTranches && t.supportTranches.length > 0)
              ? t.supportTranches
              : existing.supportTranches,
        relations:
          (existing.relations && existing.relations.length > 0)
            ? existing.relations
            : (t.relations && t.relations.length > 0)
              ? t.relations
              : existing.relations,
        // Explicit boolean merge: first defined value wins (false from data is meaningful).
        zAccrualEnabled:
          existing.zAccrualEnabled !== undefined ? existing.zAccrualEnabled
          : t.zAccrualEnabled !== undefined ? t.zAccrualEnabled
          : undefined,
      });
    } else if (t.accountType) {
      if (!ctx.accounts.has(t.name)) ctx.accounts.set(t.name, t);
    } else {
      // Residual — register as a pseudo bond
      if (!ctx.bonds.has(t.name)) ctx.bonds.set(t.name, t);
    }
  }
}

function parseScheduleContract(raw: string): Array<{ period: number; target_principal: number }> {
  const scheduleContract: Array<{ period: number; target_principal: number }> = [];
  const normalized = String(raw || "").trim();
  if (!normalized) return scheduleContract;
  const points = normalized.split(",").map((s) => s.trim()).filter(Boolean);
  points.forEach((point) => {
    const [periodText, principalText] = point.split(":");
    const period = Number(periodText);
    const principal = Number(principalText);
    if (Number.isFinite(period) && Number.isFinite(principal)) {
      scheduleContract.push({ period, target_principal: principal });
    }
  });
  return scheduleContract;
}

function buildSyntheticScheduleFromModel(opts: {
  behavior: "PAC" | "TAC";
  modelType: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
  speedLow: number | null;
  speedHigh: number | null;
  customVector: string;
}): Array<{ period: number; target_principal: number }> {
  const { behavior, modelType, speedLow, speedHigh, customVector } = opts;
  if (modelType === "CUSTOM_VECTOR") {
    const parsed = parseScheduleContract(customVector);
    if (parsed.length > 0) return parsed;
    const trimmed = customVector.trim().toLowerCase();
    if (trimmed.startsWith("ramp(")) {
      return [{ period: 1, target_principal: 1.0 }];
    }
    return [];
  }
  if (behavior === "PAC") {
    const lo = Number.isFinite(speedLow as number) ? Number(speedLow) : null;
    const hi = Number.isFinite(speedHigh as number) ? Number(speedHigh) : null;
    if (lo == null || hi == null) return [];
    return [
      { period: 1, target_principal: lo },
      { period: 2, target_principal: hi },
    ];
  }
  const tgt = Number.isFinite(speedLow as number) ? Number(speedLow) : null;
  if (tgt == null) return [];
  return [{ period: 1, target_principal: tgt }];
}

function applyPacTacSemantics(
  targets: TargetInfo[],
  {
    behavior,
    modelType,
    speedLow,
    speedHigh,
    customVector,
    priorityTier,
    dependsOn,
    supportsRaw,
  }: {
    behavior: "PAC" | "TAC";
    modelType: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
    speedLow: number | null;
    speedHigh: number | null;
    customVector: string;
    priorityTier: number | null;
    dependsOn: string | null;
    supportsRaw: string;
  },
): TargetInfo[] {
  const scheduleContract = buildSyntheticScheduleFromModel({
    behavior,
    modelType,
    speedLow,
    speedHigh,
    customVector,
  });
  const supportTranches = String(supportsRaw || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return targets.map((target) => {
    if (!target.isBond) return target;
    return {
      ...target,
      kind: behavior,
      scheduleModelType: modelType,
      schedulePriorityTier: priorityTier,
      scheduleDependsOn: dependsOn,
      scheduleSpeedLow: speedLow,
      scheduleSpeedHigh: speedHigh,
      scheduleCustomVector: customVector.trim() || null,
      scheduleContract,
      scheduleToleranceBps: null,
      supportTranches,
    };
  });
}

function emitSequential(block: any, ctx: Ctx): void {
  const payType = block.getFieldValue("PAY_TYPE") || "INTEREST";
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const ruleType = PAY_TYPE_MAP[payType] || "PAY_INTEREST";
  const targets = extractTargets(block, "TARGETS");
  registerTargets(targets, ctx);
  const maxPay = Number(block.getFieldValue("MAX_PAY")) || 0;
  const { ruleId: savedRuleId, groupId, capMode, coverageMode } = extractRuleBlockData(block);

  targets.forEach((t, i) => {
    ctx.rules.push({
      rule_id: savedRuleId || `rule_${ctx.order}`,
      rule_type: ruleType,
      order: ctx.order,
      from_sources: [source],
      to_targets: [t.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: maxPay > 0 && i === 0 ? maxPay : null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
      group_id: groupId,
      cap_mode: capMode,
      coverage_mode: coverageMode,
    });
    ctx.order++;
  });
}

function emitProRata(block: any, ctx: Ctx): void {
  const payType = block.getFieldValue("PAY_TYPE") || "PRINCIPAL";
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const ruleType = PAY_TYPE_MAP[payType] || "PAY_PRINCIPAL";
  const targets = extractTargets(block, "TARGETS");
  registerTargets(targets, ctx);

  if (targets.length === 0) return;

  const maxPay = Number(block.getFieldValue("MAX_PAY")) || 0;
  const { ruleId: savedRuleId, groupId, capMode, coverageMode } = extractRuleBlockData(block);

  ctx.rules.push({
    rule_id: savedRuleId || `rule_${ctx.order}`,
    rule_type: ruleType,
    order: ctx.order,
    from_sources: [source],
    to_targets: targets.map((t) => t.name),
    payment_style: "PRO_RATA",
    max_amount_fixed: maxPay > 0 ? maxPay : null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
    group_id: groupId,
    cap_mode: capMode,
    coverage_mode: coverageMode,
  });
  ctx.order++;
}

function emitPacTacSchedule(block: any, ctx: Ctx, behavior: "PAC" | "TAC"): void {
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const modelType = (block.getFieldValue("MODEL_TYPE") || "PSA") as "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
  const speedLowRaw = Number(block.getFieldValue("SPEED_LOW"));
  const speedHighRaw = Number(block.getFieldValue("SPEED_HIGH"));
  const speedLow = Number.isFinite(speedLowRaw) ? speedLowRaw : null;
  let speedHigh = Number.isFinite(speedHighRaw) ? speedHighRaw : null;
  if (behavior === "TAC") {
    speedHigh = speedLow;
  }
  const customVector = String(block.getFieldValue("CUSTOM_VECTOR") || "");
  const priorityTierRaw = Number(block.getFieldValue("PRIORITY_TIER"));
  const priorityTier = Number.isFinite(priorityTierRaw) ? priorityTierRaw : null;
  const dependsOnRaw = String(block.getFieldValue("DEPENDS_ON") || "").trim();
  const dependsOn = dependsOnRaw.length > 0 ? dependsOnRaw : null;
  const supportTargets = extractTargets(block, "SUPPORT_BONDS");
  const supports = extractSupportBondNames(block).join(",");
  const targets = applyPacTacSemantics(extractTargets(block, "TARGETS"), {
    behavior,
    modelType,
    speedLow,
    speedHigh,
    customVector,
    priorityTier,
    dependsOn,
    supportsRaw: supports,
  });
  registerTargets([...targets, ...supportTargets], ctx);

  const { ruleId: pacRuleId, groupId: pacGroupId, capMode: pacCapMode } = extractRuleBlockData(block);
  targets.forEach((target) => {
    ctx.rules.push({
      rule_id: pacRuleId || `${behavior.toLowerCase()}_rule_${ctx.order}`,
      rule_type: "PAY_PRINCIPAL",
      order: ctx.order,
      from_sources: [source],
      to_targets: [target.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
      group_id: pacGroupId,
      cap_mode: pacCapMode,
    });
    ctx.order++;
  });
}

function emitAccretionRedirect(block: any, ctx: Ctx): void {
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const maxPay = Number(block.getFieldValue("MAX_PAY")) || 0;
  const targets = extractTargets(block, "TARGETS");
  registerTargets(targets, ctx);
  const { ruleId: arRuleId, groupId: arGroupId } = extractRuleBlockData(block);
  targets.forEach((target, idx) => {
    ctx.rules.push({
      rule_id: arRuleId || `accretion_redirect_${ctx.order}`,
      rule_type: "PAY_PRINCIPAL",
      order: ctx.order,
      from_sources: [source],
      to_targets: [target.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: maxPay > 0 && idx === 0 ? maxPay : null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
      group_id: arGroupId,
    });
    ctx.order++;
  });
}

function emitFee(block: any, ctx: Ctx): void {
  const payee = block.getFieldValue("PAYEE") || "SERVICER";
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const basis = block.getFieldValue("BASIS") || "FIXED_DOLLAR";
  const canonicalBasis = FEE_BASIS_MAP[basis] || basis;
  const amount = Number(block.getFieldValue("AMOUNT")) || 0;
  const frequency = block.getFieldValue("FREQ") || "MONTHLY";
  const isPctPoolBps = basis === "PCT_POOL";
  const { ruleId: feeRuleId, groupId: feeGroupId } = extractRuleBlockData(block);

  ctx.fees.push({
    name: payee,
    basis_type: canonicalBasis,
    amount: isPctPoolBps ? 0 : amount,
    // UI stores annual bps (25 = 0.25% annual rate).
    rate: isPctPoolBps ? amount / 100 : null,
    frequency,
  });

  ctx.rules.push({
    rule_id: feeRuleId || `fee_${ctx.order}`,
    rule_type: "PAY_FEE",
    order: ctx.order,
    from_sources: [source],
    to_targets: [payee],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: !isPctPoolBps && amount > 0 ? amount : null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
    group_id: feeGroupId,
  });
  ctx.order++;
}

function emitTrigger(block: any, ctx: Ctx): void {
  const name = block.getFieldValue("TRIGGER_NAME") || "TRIGGER";
  const metric = block.getFieldValue("METRIC") || "CUSTOM";
  const canonicalMetric = TRIGGER_METRIC_MAP[metric] || metric;
  const threshold = block.getFieldValue("THRESHOLD") || 0;

  ctx.triggers.push({ name, metric_type: canonicalMetric, threshold_value: threshold });

  const outerTrig = ctx.activeTrigger;
  const outerInv = ctx.conditionInvert;
  ctx.activeTrigger = name;

  ctx.conditionInvert = false;
  walkWaterfall(getStatementChain(block, "RULES"), ctx);

  ctx.conditionInvert = true;
  walkWaterfall(getStatementChain(block, "ELSE_RULES"), ctx);

  ctx.activeTrigger = outerTrig;
  ctx.conditionInvert = outerInv;
}

// ---------------------------------------------------------------------------
// Top-level generator
// ---------------------------------------------------------------------------

export function generateDealIR(workspace: any): DealDefinitionIR {
  // Collect all top-level waterfall blocks (no deal_root needed)
  const allBlocks = workspace.getTopBlocks(true);
  const waterfallBlocks = allBlocks.filter((b: any) =>
    [
      "pay_sequential",
      "pay_pro_rata",
      "pay_pac_schedule",
      "pay_tac_schedule",
      "pay_accretion_redirect",
      "pay_fee",
      "split_account",
      "trigger_wrapper",
    ].includes(b.type)
  );

  // Flatten chains (top blocks + their next connections)
  const fullChain: any[] = [];
  for (const top of waterfallBlocks) {
    for (const b of walkChain(top)) {
      if (!fullChain.includes(b)) fullChain.push(b);
    }
  }

  if (fullChain.length === 0) {
    throw new Error("No pay rules found. Drag Pay Sequential or Pay Pro Rata from the toolbox.");
  }

  const ctx: Ctx = {
    order: 0,
    rules: [],
    fees: [],
    triggers: [],
    bonds: new Map(),
    accounts: new Map(),
    activeTrigger: null,
    conditionInvert: false,
  };

  walkWaterfall(fullChain, ctx);

  // Build bond defs from collected targets
  const bonds: BondDefIR[] = [];
  for (const [name, info] of ctx.bonds) {
    const resolvedKind = info.kind || (info.payMode === "PIK" ? "Z" : "CASH_PAY");
    bonds.push({
      name,
      kind: resolvedKind,
      group_id: info.groupId ?? null,
      coupon: info.coupon || 0,
      notional_pct_of_collateral: Number(info.sizePctPool || 0),
      notional: info.faceAmt || 0,
      is_bond: true,
      is_pseudo: info.faceAmt === 0,
      coupon_type: info.bondType || "FIXED",
      index_name: info.bondType === "FLOATING" ? (info.indexName ?? null) : null,
      margin: info.bondType === "FLOATING" ? Number(info.margin || 0) : null,
      pay_mode: info.payMode || "CASH_PAY",
      schedule_model_type: info.scheduleModelType ?? null,
      schedule_priority_tier: info.schedulePriorityTier ?? null,
      schedule_depends_on: info.scheduleDependsOn ?? null,
      schedule_speed_low: info.scheduleSpeedLow ?? null,
      schedule_speed_high: info.scheduleSpeedHigh ?? null,
      schedule_custom_vector: info.scheduleCustomVector ?? null,
      schedule_contract: info.scheduleContract || [],
      schedule_tolerance_bps:
        resolvedKind === "PAC" || resolvedKind === "TAC"
          ? (info.scheduleToleranceBps ?? 25)
          : null,
      relations: (() => {
        if (info.relations && info.relations.length > 0) return info.relations;
        if (resolvedKind === "PAC" || resolvedKind === "TAC") {
          const supports = (info.supportTranches || []).filter(Boolean);
          return supports.length > 0
            ? [{ relation_type: "SUPPORTED_BY", targets: supports }]
            : [];
        }
        return [];
      })(),
      z_accrual_enabled: info.zAccrualEnabled ?? resolvedKind === "Z",
      z_release_trigger: info.zReleaseTrigger ?? null,
    });
  }

  // Always add residual
  if (!ctx.bonds.has("R") && !bonds.find((b) => b.kind === "RESIDUAL")) {
    bonds.push({
      name: "R", kind: "RESIDUAL", coupon: 0, notional_pct_of_collateral: 0, notional: 0,
      is_bond: false, is_pseudo: true, coupon_type: "FIXED", index_name: null, margin: null,
      pay_mode: "CASH_PAY",
      schedule_contract: [], schedule_tolerance_bps: null,
      schedule_model_type: null, schedule_priority_tier: null, schedule_depends_on: null, schedule_speed_low: null, schedule_speed_high: null, schedule_custom_vector: null,
      relations: [], z_accrual_enabled: false, z_release_trigger: null,
    });
  }

  // Build account defs
  const accounts: AccountDefIR[] = [];
  for (const [name, info] of ctx.accounts) {
    const mode = info.initialMode || "PCT_STACK";
    const amt = info.initialAmt ?? 0;
    const isDollar = mode === "FIXED_DOLLAR";
    accounts.push({
      name,
      account_category: info.accountType || name,
      starting_amount: isDollar ? amt : 0,
      starting_pct: isDollar ? null : amt,
      starting_basis: isDollar ? "FIXED_DOLLAR" : "NOTE_BALANCE",
    });
  }

  // Add pseudo bonds for fees the runtime needs
  const bondNames = new Set(bonds.map((b) => b.name));
  for (const fee of ctx.fees) {
    if (!bondNames.has(fee.name)) {
      bonds.push({
        name: fee.name, kind: "PSEUDO", coupon: 0, notional_pct_of_collateral: 0, notional: 0,
        is_bond: false, is_pseudo: true, coupon_type: "FIXED", index_name: null, margin: null,
        pay_mode: "CASH_PAY",
        schedule_contract: [], schedule_tolerance_bps: null,
        schedule_model_type: null, schedule_priority_tier: null, schedule_depends_on: null, schedule_speed_low: null, schedule_speed_high: null, schedule_custom_vector: null,
        relations: [], z_accrual_enabled: false, z_release_trigger: null,
      });
      bondNames.add(fee.name);
    }
  }

  // Derive collateral_groups from unique non-null group_id values on bonds and rules.
  // This is required: the backend rejects any group_id on bonds/rules when
  // collateral_groups is absent or empty.
  const groupIdSet = new Set<string>();
  for (const b of bonds) {
    if (b.group_id) groupIdSet.add(b.group_id);
  }
  for (const r of ctx.rules) {
    if (r.group_id) groupIdSet.add(r.group_id);
  }
  const collateral_groups: CollateralGroupDefIR[] = Array.from(groupIdSet).sort().map((gid) => ({
    group_id: gid,
    label: gid,
    description: "",
  }));

  return {
    schema_version: "2.0.0",
    deal_name: "Deal",
    bonds,
    accounts,
    fees: ctx.fees,
    triggers: ctx.triggers,
    waterfall_rules: ctx.rules,
    collateral_groups,
    deal_knobs: {},
  };
}
