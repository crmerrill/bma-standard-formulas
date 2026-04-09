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
  size_pct: number;
  size_dollars: number;
  is_bond: boolean;
  is_pseudo: boolean;
  coupon_type: string;
}

interface AccountDefIR {
  name: string;
  account_type: string;
  starting_amount: number;
  starting_pct: number | null;
  starting_basis: string;
}

interface FeeDefIR {
  name: string;
  basis_type: string;
  amount: number;
  /** Basis points when basis_type is PCT_POOL; otherwise null */
  bps: number | null;
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

// ---------------------------------------------------------------------------
// Target extraction (bonds + accounts from inside pay rules)
// ---------------------------------------------------------------------------

interface TargetInfo {
  name: string;
  isBond: boolean;
  bondType?: string;
  faceAmt?: number;
  coupon?: number;
  accrual?: string;
  accountType?: string;
  /** PCT_STACK = % of total bond face; FIXED_DOLLAR = $ */
  initialMode?: string;
  initialAmt?: number;
}

function extractTargets(ruleBlock: any): TargetInfo[] {
  const targets: TargetInfo[] = [];
  for (const t of getStatementChain(ruleBlock, "TARGETS")) {
    if (t.type === "bond_target") {
      targets.push({
        name: t.getFieldValue("NAME") || "X",
        isBond: true,
        bondType: t.getFieldValue("BOND_TYPE") || "FIXED",
        faceAmt: t.getFieldValue("FACE_AMT") || 0,
        coupon: t.getFieldValue("COUPON") || 0,
        accrual: t.getFieldValue("ACCRUAL") || "30_360",
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
      case "pay_fee": emitFee(b, ctx); break;
      case "trigger_wrapper": emitTrigger(b, ctx); break;
      case "split_account": break; // account-level, no rule emitted
    }
  }
}

function registerTargets(targets: TargetInfo[], ctx: Ctx): void {
  for (const t of targets) {
    if (t.isBond) {
      if (!ctx.bonds.has(t.name)) ctx.bonds.set(t.name, t);
    } else if (t.accountType) {
      if (!ctx.accounts.has(t.name)) ctx.accounts.set(t.name, t);
    } else {
      // Residual — register as a pseudo bond
      if (!ctx.bonds.has(t.name)) ctx.bonds.set(t.name, t);
    }
  }
}

function emitSequential(block: any, ctx: Ctx): void {
  const payType = block.getFieldValue("PAY_TYPE") || "INTEREST";
  const source = block.getFieldValue("SOURCE") || "COLLECTION";
  const ruleType = PAY_TYPE_MAP[payType] || "PAY_INTEREST";
  const targets = extractTargets(block);
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
  const source = block.getFieldValue("SOURCE") || "COLLECTION";
  const ruleType = PAY_TYPE_MAP[payType] || "PAY_PRINCIPAL";
  const targets = extractTargets(block);
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

function emitFee(block: any, ctx: Ctx): void {
  const payee = block.getFieldValue("PAYEE") || "SERVICER";
  const source = block.getFieldValue("SOURCE") || "COLLECTION";
  const basis = block.getFieldValue("BASIS") || "FIXED_DOLLAR";
  const amount = Number(block.getFieldValue("AMOUNT")) || 0;
  const isBps = basis === "PCT_POOL";

  ctx.fees.push({
    name: payee,
    basis_type: basis,
    amount: isBps ? 0 : amount,
    bps: isBps ? amount : null,
  });

  ctx.rules.push({
    rule_id: `fee_${ctx.order}`,
    rule_type: "PAY_FEE",
    order: ctx.order,
    from_sources: [source],
    to_targets: [payee],
    payment_style: "SEQUENTIAL",
    max_amount_fixed: !isBps && amount > 0 ? amount : null,
    condition_trigger: ctx.activeTrigger,
    condition_invert: ctx.conditionInvert,
  });
  ctx.order++;
}

function emitTrigger(block: any, ctx: Ctx): void {
  const name = block.getFieldValue("TRIGGER_NAME") || "TRIGGER";
  const metric = block.getFieldValue("METRIC") || "CUSTOM";
  const threshold = block.getFieldValue("THRESHOLD") || 0;

  ctx.triggers.push({ name, metric_type: metric, threshold_value: threshold });

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
    ["pay_sequential", "pay_pro_rata", "pay_fee", "split_account", "trigger_wrapper"].includes(b.type)
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
      tranche_type: "SEQUENTIAL",
      coupon: info.coupon || 0,
      size_pct: 0,
      size_dollars: info.faceAmt || 0,
      is_bond: true,
      is_pseudo: info.faceAmt === 0,
      coupon_type: info.bondType || "FIXED",
    });
  }

  // Always add residual
  if (!ctx.bonds.has("R") && !bonds.find((b) => b.tranche_type === "RESIDUAL")) {
    bonds.push({
      name: "R", tranche_type: "RESIDUAL", coupon: 0, size_pct: 0, size_dollars: 0,
      is_bond: false, is_pseudo: true, coupon_type: "FIXED",
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
      account_type: info.accountType || name,
      starting_amount: isDollar ? amt : 0,
      starting_pct: isDollar ? null : amt,
      starting_basis: isDollar ? "FIXED_DOLLAR" : "NOTE_BALANCE",
    });
  }

  // Add pseudo bonds for fees and accounts the runtime needs
  const bondNames = new Set(bonds.map((b) => b.name));
  for (const fee of ctx.fees) {
    if (!bondNames.has(fee.name)) {
      bonds.push({
        name: fee.name, tranche_type: "PSEUDO", coupon: 0, size_pct: 0, size_dollars: 0,
        is_bond: false, is_pseudo: true, coupon_type: "FIXED",
      });
      bondNames.add(fee.name);
    }
  }
  for (const acct of accounts) {
    if (!bondNames.has(acct.name)) {
      bonds.push({
        name: acct.name, tranche_type: "PSEUDO", coupon: 0, size_pct: 0, size_dollars: 0,
        is_bond: false, is_pseudo: true, coupon_type: "FIXED",
      });
      bondNames.add(acct.name);
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
