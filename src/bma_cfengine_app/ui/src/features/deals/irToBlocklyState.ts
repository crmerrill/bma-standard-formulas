/**
 * IR -> Blockly serialization state synthesizer.
 *
 * Companion to ``irGenerator.ts`` (workspace -> IR). When a deal is
 * loaded that has no saved Blockly layout (e.g., it was seeded via a
 * Python script outside the Studio), this module synthesizes a
 * Blockly serialization-state JSON from the deal IR so the canvas
 * auto-populates and the user can inspect / edit the deal visually
 * without having to rebuild blocks by hand.
 *
 * Coverage in iteration 1 (this file):
 *
 *   - PAY_FEE rules + corresponding `fees[]` entries -> pay_fee blocks.
 *   - PAY_INTEREST / PAY_PRINCIPAL rules with payment_style=SEQUENTIAL
 *     or PRO_RATA -> pay_sequential / pay_pro_rata blocks.
 *   - SPLIT_CASH rules -> split_account blocks.
 *   - Trigger-gated rules -> wrapped in `trigger_wrapper` blocks.
 *   - Bond, account, residual targets inside the rule's TARGETS slot.
 *
 * Deferred (iteration 2):
 *
 *   - PAC/TAC/Z schedule rules (pay_pac_schedule, pay_tac_schedule,
 *     pay_accretion_redirect). Those carry schedule contracts and
 *     support-tranche relationships that the simple synthesizer
 *     can't reconstruct deterministically yet. Deals with those
 *     structures (e.g., FNR 2006-018) will get the simpler rules
 *     synthesized but PAC/TAC/Z bonds will appear as plain bonds.
 */

interface IRBond {
  name: string;
  tranche_type?: string;
  coupon?: number;
  size_dollars?: number;
  size_pct?: number | null;
  pay_mode?: string;
  coupon_type?: string;
  index_name?: string | null;
  margin?: number | null;
  is_pseudo?: boolean;
}

interface IRFee {
  name: string;
  basis_type: string;
  amount?: number;
  rate?: number | null;
  frequency?: string;
}

interface IRTrigger {
  name: string;
  metric_type: string;
  threshold_value: number;
}

interface IRRule {
  rule_id: string;
  rule_type: string;
  order: number;
  from_sources?: string[];
  to_targets?: string[];
  payment_style?: string;
  max_amount_fixed?: number | null;
  condition_trigger?: string | null;
  condition_invert?: boolean | null;
  target_weights?: number[] | null;
}

export interface IRForSynthesis {
  bonds?: IRBond[];
  fees?: IRFee[];
  triggers?: IRTrigger[];
  waterfall_rules?: IRRule[];
}

/**
 * Inverse of `FEE_BASIS_MAP` in irGenerator: canonical -> UI value.
 */
const FEE_BASIS_INVERSE: Record<string, string> = {
  COLLATERAL_BALANCE: "PCT_POOL",
  FIXED_DOLLAR: "FIXED_DOLLAR",
  PER_LOAN: "PER_LOAN",
};

/**
 * Inverse of `_LEGACY_RULE_SOURCE_MAP` etc: any source name canonicalized
 * to "CASH" maps back to the UI-friendly "COLLECTION" by default. Other
 * pseudo-source ledgers (INT_CASH, PRIN_CASH, virtual SPLIT_CASH stream
 * names) are passed through.
 */
function ruleSourceForUI(source: string): string {
  if (source === "CASH") return "COLLECTION";
  return source;
}

/**
 * Inverse of `TRIGGER_METRIC_MAP`: canonical -> UI value.
 */
const TRIGGER_METRIC_INVERSE: Record<string, string> = {
  CUMULATIVE_LOSS: "CUM_LOSS",
  CUMULATIVE_DEFAULT: "CUM_DEFAULT",
  DELINQUENCY_RATE: "DELINQUENCY",
  OC_TEST: "OC_RATIO",
  IC_TEST: "IC_RATIO",
  CUSTOM: "CUSTOM",
};

interface BlocklyBlock {
  type: string;
  fields?: Record<string, string | number | boolean>;
  inputs?: Record<string, { block: BlocklyBlock }>;
  next?: { block: BlocklyBlock };
  // x/y are only set on top-level blocks.
  x?: number;
  y?: number;
}

interface BlocklyWorkspaceState {
  blocks: {
    languageVersion: 0;
    blocks: BlocklyBlock[];
  };
}

/**
 * Synthesize a Blockly workspace state from a deal IR. The result can
 * be passed to `Blockly.serialization.workspaces.load(state, workspace)`.
 *
 * Returns null when the IR has no synthesizable rules (in which case
 * the caller should leave the canvas empty).
 */
export function synthesizeWorkspaceState(
  ir: IRForSynthesis,
): BlocklyWorkspaceState | null {
  const rules = (ir.waterfall_rules ?? []).slice().sort(
    (a, b) => (a.order ?? 0) - (b.order ?? 0),
  );
  const bondByName = new Map<string, IRBond>();
  for (const b of ir.bonds ?? []) {
    if (b?.name) bondByName.set(b.name, b);
  }
  const feeByName = new Map<string, IRFee>();
  for (const f of ir.fees ?? []) {
    if (f?.name) feeByName.set(f.name, f);
  }
  const triggerByName = new Map<string, IRTrigger>();
  for (const t of ir.triggers ?? []) {
    if (t?.name) triggerByName.set(t.name, t);
  }

  // Group consecutive rules under the same trigger so we can wrap them
  // in one trigger_wrapper. Rules with no trigger are at the top level.
  // (This matches the auto-save shape: `IF X > t THEN [...rules...]`).
  type Group =
    | { kind: "rule"; rule: IRRule }
    | { kind: "trigger"; triggerName: string; invert: boolean; rules: IRRule[] };

  const groups: Group[] = [];
  for (const rule of rules) {
    const trigger = rule.condition_trigger ?? null;
    if (!trigger) {
      groups.push({ kind: "rule", rule });
      continue;
    }
    const invert = !!rule.condition_invert;
    const last = groups[groups.length - 1];
    if (
      last
      && last.kind === "trigger"
      && last.triggerName === trigger
      && last.invert === invert
    ) {
      last.rules.push(rule);
    } else {
      groups.push({
        kind: "trigger",
        triggerName: trigger,
        invert,
        rules: [rule],
      });
    }
  }

  const ruleBlocks: BlocklyBlock[] = [];
  for (const group of groups) {
    if (group.kind === "rule") {
      const blk = ruleToBlock(group.rule, bondByName, feeByName);
      if (blk) ruleBlocks.push(blk);
    } else {
      const trig = triggerByName.get(group.triggerName);
      if (!trig) continue;
      const inner = chainBlocks(
        group.rules
          .map((r) => ruleToBlock(r, bondByName, feeByName))
          .filter((b): b is BlocklyBlock => b !== null),
      );
      if (!inner) continue;
      const triggerBlock: BlocklyBlock = {
        type: "trigger_wrapper",
        fields: {
          TRIGGER_NAME: trig.name,
          METRIC: TRIGGER_METRIC_INVERSE[trig.metric_type] ?? "CUSTOM",
          THRESHOLD: trig.threshold_value,
        },
        inputs: {
          [group.invert ? "ELSE_RULES" : "RULES"]: { block: inner },
        },
      };
      ruleBlocks.push(triggerBlock);
    }
  }

  const chained = chainBlocks(ruleBlocks);
  if (!chained) return null;
  // Position the chain at a stable origin so the user lands somewhere
  // sensible after Blockly auto-loads. Subsequent edits will move
  // blocks freely.
  chained.x = 80;
  chained.y = 60;

  return {
    blocks: {
      languageVersion: 0,
      blocks: [chained],
    },
  };
}

/**
 * Splice an array of free-standing blocks into a single linked chain via
 * the `next` pointer. Returns null on an empty input.
 */
function chainBlocks(blocks: BlocklyBlock[]): BlocklyBlock | null {
  if (blocks.length === 0) return null;
  const head = blocks[0];
  let cursor = head;
  for (let i = 1; i < blocks.length; i++) {
    cursor.next = { block: blocks[i] };
    cursor = blocks[i];
  }
  return head;
}

function ruleToBlock(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
  feeByName: Map<string, IRFee>,
): BlocklyBlock | null {
  switch (rule.rule_type) {
    case "PAY_FEE":
      return feeRuleToBlock(rule, feeByName);
    case "PAY_INTEREST":
    case "PAY_PRINCIPAL":
      return waterfallRuleToBlock(rule, bondByName);
    case "SPLIT_CASH":
      return splitCashRuleToBlock(rule);
    default:
      // Unsupported rule types in this iteration (PAC/TAC/Z schedule,
      // accretion redirect). Synthesizing them is deferred. Returning
      // null here is intentional: the deal still has the rule in IR,
      // it just won't appear as a visual block until the synthesizer
      // is extended.
      return null;
  }
}

function feeRuleToBlock(
  rule: IRRule,
  feeByName: Map<string, IRFee>,
): BlocklyBlock | null {
  const payee = (rule.to_targets ?? [])[0];
  if (!payee) return null;
  const fee = feeByName.get(payee);
  const basisCanonical = fee?.basis_type ?? "FIXED_DOLLAR";
  const basis = FEE_BASIS_INVERSE[basisCanonical] ?? basisCanonical;
  const isPctPoolBps = basis === "PCT_POOL";
  // Inverse of irGenerator's `rate: amount / 100` for PCT_POOL fees.
  const amount = isPctPoolBps
    ? Math.round((fee?.rate ?? 0) * 100 * 100) / 100
    : (fee?.amount ?? 0);
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  return {
    type: "pay_fee",
    fields: {
      PAYEE: payee,
      SOURCE: source,
      BASIS: basis,
      AMOUNT: amount,
      FREQ: fee?.frequency ?? "MONTHLY",
    },
  };
}

function waterfallRuleToBlock(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
): BlocklyBlock | null {
  const payType = rule.rule_type === "PAY_PRINCIPAL" ? "PRINCIPAL" : "INTEREST";
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  const targets = (rule.to_targets ?? []).map((name) =>
    targetToBlock(name, bondByName),
  );
  const targetChain = chainBlocks(
    targets.filter((t): t is BlocklyBlock => t !== null),
  );
  if (!targetChain) return null;

  const payment_style = rule.payment_style ?? "SEQUENTIAL";
  if (payment_style === "PRO_RATA") {
    return {
      type: "pay_pro_rata",
      fields: {
        PAY_TYPE: payType,
        SOURCE: source,
        BASIS: "BALANCE",
        MAX_PAY: rule.max_amount_fixed ?? 0,
      },
      inputs: { TARGETS: { block: targetChain } },
    };
  }

  return {
    type: "pay_sequential",
    fields: {
      PAY_TYPE: payType,
      SOURCE: source,
      LIMIT: "UNTIL_ZERO",
      MAX_PAY: rule.max_amount_fixed ?? 0,
    },
    inputs: { TARGETS: { block: targetChain } },
  };
}

function splitCashRuleToBlock(rule: IRRule): BlocklyBlock | null {
  const targets = rule.to_targets ?? [];
  if (targets.length < 2) return null;
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  return {
    type: "split_account",
    fields: {
      SOURCE: source,
      OUT_1: targets[0],
      OUT_2: targets[1],
    },
  };
}

/**
 * Convert a target name to its corresponding target_item block. Looks
 * up the bond definition; falls back to a residual_target for "R" and
 * an account_target for everything else.
 */
function targetToBlock(
  name: string,
  bondByName: Map<string, IRBond>,
): BlocklyBlock | null {
  const bond = bondByName.get(name);
  if (bond && (bond.is_pseudo === false || bond.tranche_type !== "PSEUDO")) {
    if (bond.tranche_type === "RESIDUAL" || name === "R") {
      return {
        type: "residual_target",
        fields: { NAME: name, SHARE_PCT: 0 },
      };
    }
    return {
      type: "bond_target",
      fields: {
        NAME: name,
        BOND_TYPE: bond.coupon_type ?? "FIXED",
        PAY_MODE: bond.pay_mode ?? "CASH_PAY",
        FACE_AMT: bond.size_dollars ?? 0,
        SIZE_PCT_POOL: bond.size_pct ?? 0,
        COUPON: bond.coupon ?? 0,
        INDEX_LABEL: "idx",
        INDEX_NAME: bond.index_name ?? "SOFR",
        SPREAD_LABEL: "sprd",
        MARGIN: bond.margin ?? 0,
        ACCRUAL: "30_360",
      },
    };
  }
  // Treat unknown target as an account target by default. Account
  // initial mode is unknown from a rule alone; use an empty default.
  return {
    type: "account_target",
    fields: {
      ACCOUNT_TYPE: name,
      INITIAL_MODE: "PCT_STACK",
      INITIAL_AMT: 0,
    },
  };
}
