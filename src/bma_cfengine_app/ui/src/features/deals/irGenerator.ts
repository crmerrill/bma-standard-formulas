/**
 * Blockly workspace -> DealDefinition IR generator.
 *
 * Scans all top-level waterfall blocks on the workspace (no Deal root needed).
 * Extracts bond/account definitions from target pieces inside pay rules.
 */

interface BondDefIR {
  name: string;
  tranche_type: string;
  coupon: number;
  notional_pct_of_collateral: number;
  notional: number;
  is_bond: boolean;
  is_pseudo: boolean;
  coupon_type: string;
  index_name: string | null;
  margin: number | null;
  pay_mode: "CASH_PAY" | "PIK";
  tranche_behavior: "SEQUENTIAL" | "PAC" | "TAC" | "Z" | "ACCRETION_DIRECTED";
  schedule_model_type: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR" | null;
  schedule_priority_tier: number | null;
  schedule_depends_on: string | null;
  schedule_speed_low: number | null;
  schedule_speed_high: number | null;
  schedule_speed_target: number | null;
  schedule_custom_vector: string | null;
  schedule_contract: Array<{ period: number; target_principal: number }>;
  schedule_tolerance_bps: number | null;
  support_tranches: string[];
  supported_by_tranches: string[];
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
}

export interface DealDefinitionIR {
  schema_version: string;
  deal_name: string;
  bonds: BondDefIR[];
  accounts: AccountDefIR[];
  fees: FeeDefIR[];
  triggers: TriggerNodeIR[];
  waterfall_rules: RuleNodeIR[];
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
  PRIN_COLLECTION: "CASH",
  INT_COLLECTION: "CASH",
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
};

function normalizeRuleSource(source: string | null | undefined): string {
  const token = source || "COLLECTION";
  return RULE_SOURCE_MAP[token] || "CASH";
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
  trancheBehavior?: "SEQUENTIAL" | "PAC" | "TAC" | "Z" | "ACCRETION_DIRECTED";
  scheduleModelType?: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
  schedulePriorityTier?: number | null;
  scheduleDependsOn?: string | null;
  scheduleSpeedLow?: number | null;
  scheduleSpeedHigh?: number | null;
  scheduleSpeedTarget?: number | null;
  scheduleCustomVector?: string | null;
  scheduleContract?: Array<{ period: number; target_principal: number }>;
  scheduleToleranceBps?: number | null;
  supportTranches?: string[];
  zReleaseTrigger?: string | null;
  accountType?: string;
  /** PCT_STACK = % of total bond face; FIXED_DOLLAR = $ */
  initialMode?: string;
  initialAmt?: number;
}

function extractTargets(ruleBlock: any, inputName = "TARGETS"): TargetInfo[] {
  const targets: TargetInfo[] = [];
  for (const t of getStatementChain(ruleBlock, inputName)) {
    if (t.type === "bond_target") {
      const bondType = t.getFieldValue("BOND_TYPE") || "FIXED";
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
        scheduleContract: [],
        scheduleToleranceBps: null,
        supportTranches: [],
        zReleaseTrigger: null,
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
      case "split_account": break; // account-level, no rule emitted
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
      ctx.bonds.set(t.name, {
        ...existing,
        ...t,
        scheduleContract:
          (t.scheduleContract && t.scheduleContract.length > 0)
            ? t.scheduleContract
            : existing.scheduleContract,
        scheduleToleranceBps:
          t.scheduleToleranceBps != null ? t.scheduleToleranceBps : existing.scheduleToleranceBps,
        supportTranches:
          (t.supportTranches && t.supportTranches.length > 0)
            ? t.supportTranches
            : existing.supportTranches,
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
  speedTarget: number | null;
  customVector: string;
}): Array<{ period: number; target_principal: number }> {
  const { behavior, modelType, speedLow, speedHigh, speedTarget, customVector } = opts;
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
  const tgt = Number.isFinite(speedTarget as number) ? Number(speedTarget) : null;
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
    speedTarget,
    customVector,
    priorityTier,
    dependsOn,
    supportsRaw,
  }: {
    behavior: "PAC" | "TAC";
    modelType: "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
    speedLow: number | null;
    speedHigh: number | null;
    speedTarget: number | null;
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
    speedTarget,
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
      trancheBehavior: behavior,
      scheduleModelType: modelType,
      schedulePriorityTier: priorityTier,
      scheduleDependsOn: dependsOn,
      scheduleSpeedLow: speedLow,
      scheduleSpeedHigh: speedHigh,
      scheduleSpeedTarget: speedTarget,
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

  targets.forEach((t, i) => {
    ctx.rules.push({
      rule_id: `rule_${ctx.order}`,
      rule_type: ruleType,
      order: ctx.order,
      from_sources: [source],
      to_targets: [t.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: maxPay > 0 && i === 0 ? maxPay : null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
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

  ctx.rules.push({
    rule_id: `rule_${ctx.order}`,
    rule_type: ruleType,
    order: ctx.order,
    from_sources: [source],
    to_targets: targets.map((t) => t.name),
    payment_style: "PRO_RATA",
    max_amount_fixed: maxPay > 0 ? maxPay : null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
  });
  ctx.order++;
}

function emitPacTacSchedule(block: any, ctx: Ctx, behavior: "PAC" | "TAC"): void {
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const modelType = (block.getFieldValue("MODEL_TYPE") || "PSA") as "PSA" | "CPR" | "ABS" | "CUSTOM_VECTOR";
  const speedLowRaw = Number(block.getFieldValue("SPEED_LOW"));
  const speedHighRaw = Number(block.getFieldValue("SPEED_HIGH"));
  const speedTargetRaw = Number(block.getFieldValue("SPEED_TARGET"));
  const speedLow = Number.isFinite(speedLowRaw) ? speedLowRaw : null;
  const speedHigh = Number.isFinite(speedHighRaw) ? speedHighRaw : null;
  const speedTarget = Number.isFinite(speedTargetRaw) ? speedTargetRaw : null;
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
    speedTarget,
    customVector,
    priorityTier,
    dependsOn,
    supportsRaw: supports,
  });
  registerTargets([...targets, ...supportTargets], ctx);

  targets.forEach((target) => {
    ctx.rules.push({
      rule_id: `${behavior.toLowerCase()}_rule_${ctx.order}`,
      rule_type: "PAY_PRINCIPAL",
      order: ctx.order,
      from_sources: [source],
      to_targets: [target.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
    });
    ctx.order++;
  });
}

function emitAccretionRedirect(block: any, ctx: Ctx): void {
  const source = normalizeRuleSource(block.getFieldValue("SOURCE"));
  const maxPay = Number(block.getFieldValue("MAX_PAY")) || 0;
  const targets = extractTargets(block, "TARGETS");
  registerTargets(targets, ctx);
  targets.forEach((target, idx) => {
    ctx.rules.push({
      rule_id: `accretion_redirect_${ctx.order}`,
      rule_type: "PAY_PRINCIPAL",
      order: ctx.order,
      from_sources: [source],
      to_targets: [target.name],
      payment_style: "SEQUENTIAL",
      max_amount_fixed: maxPay > 0 && idx === 0 ? maxPay : null,
      condition_trigger: ctx.activeTrigger,
      condition_invert: ctx.conditionInvert,
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

  ctx.fees.push({
    name: payee,
    basis_type: canonicalBasis,
    amount: isPctPoolBps ? 0 : amount,
    // UI stores annual bps (25 = 0.25% annual rate).
    rate: isPctPoolBps ? amount / 100 : null,
    frequency,
  });

  ctx.rules.push({
    rule_id: `fee_${ctx.order}`,
    rule_type: "PAY_FEE",
    order: ctx.order,
    from_sources: [source],
    to_targets: [payee],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: !isPctPoolBps && amount > 0 ? amount : null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
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
    bonds.push({
      name,
      tranche_type:
        info.trancheBehavior === "Z" || info.payMode === "PIK"
          ? "Z_BOND"
          : info.trancheBehavior === "ACCRETION_DIRECTED"
            ? "ACCRETION_DIRECTED"
            : "SEQUENTIAL",
      coupon: info.coupon || 0,
      notional_pct_of_collateral: Number(info.sizePctPool || 0),
      notional: info.faceAmt || 0,
      is_bond: true,
      is_pseudo: info.faceAmt === 0,
      coupon_type: info.bondType || "FIXED",
      index_name: info.bondType === "FLOATING" ? (info.indexName ?? null) : null,
      margin: info.bondType === "FLOATING" ? Number(info.margin || 0) : null,
      pay_mode: info.payMode || "CASH_PAY",
      tranche_behavior: info.trancheBehavior || (info.payMode === "PIK" ? "Z" : "SEQUENTIAL"),
      schedule_model_type: info.scheduleModelType ?? null,
      schedule_priority_tier: info.schedulePriorityTier ?? null,
      schedule_depends_on: info.scheduleDependsOn ?? null,
      schedule_speed_low: info.scheduleSpeedLow ?? null,
      schedule_speed_high: info.scheduleSpeedHigh ?? null,
      schedule_speed_target: info.scheduleSpeedTarget ?? null,
      schedule_custom_vector: info.scheduleCustomVector ?? null,
      schedule_contract: info.scheduleContract || [],
      schedule_tolerance_bps:
        info.trancheBehavior === "PAC" || info.trancheBehavior === "TAC"
          ? (info.scheduleToleranceBps ?? 25)
          : null,
      support_tranches: info.supportTranches || [],
      supported_by_tranches: info.supportTranches || [],
      z_accrual_enabled: (info.trancheBehavior || (info.payMode === "PIK" ? "Z" : "SEQUENTIAL")) === "Z",
      z_release_trigger: info.zReleaseTrigger ?? null,
    });
  }

  // Always add residual
  if (!ctx.bonds.has("R") && !bonds.find((b) => b.tranche_type === "RESIDUAL")) {
    bonds.push({
      name: "R", tranche_type: "RESIDUAL", coupon: 0, notional_pct_of_collateral: 0, notional: 0,
      is_bond: false, is_pseudo: true, coupon_type: "FIXED", index_name: null, margin: null,
      pay_mode: "CASH_PAY",
      tranche_behavior: "SEQUENTIAL", schedule_contract: [], schedule_tolerance_bps: null,
      schedule_model_type: null, schedule_priority_tier: null, schedule_depends_on: null, schedule_speed_low: null, schedule_speed_high: null, schedule_speed_target: null, schedule_custom_vector: null,
      support_tranches: [], supported_by_tranches: [], z_accrual_enabled: false, z_release_trigger: null,
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
        name: fee.name, tranche_type: "PSEUDO", coupon: 0, notional_pct_of_collateral: 0, notional: 0,
        is_bond: false, is_pseudo: true, coupon_type: "FIXED", index_name: null, margin: null,
        pay_mode: "CASH_PAY",
        tranche_behavior: "SEQUENTIAL", schedule_contract: [], schedule_tolerance_bps: null,
        schedule_model_type: null, schedule_priority_tier: null, schedule_depends_on: null, schedule_speed_low: null, schedule_speed_high: null, schedule_speed_target: null, schedule_custom_vector: null,
        support_tranches: [], supported_by_tranches: [], z_accrual_enabled: false, z_release_trigger: null,
      });
      bondNames.add(fee.name);
    }
  }

  return {
    schema_version: "1.0.0",
    deal_name: "Deal",
    bonds,
    accounts,
    fees: ctx.fees,
    triggers: ctx.triggers,
    waterfall_rules: ctx.rules,
    deal_knobs: {},
  };
}
