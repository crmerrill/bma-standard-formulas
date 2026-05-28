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
 * Coverage:
 *
 *   - PAY_FEE, PAY_INTEREST, PAY_PRINCIPAL, PAY_INTEREST_SHORTFALL,
 *     PAY_WRITEDOWN, PAY_RESIDUAL rules -> pay_fee / pay_sequential /
 *     pay_pro_rata blocks with the right PAY_TYPE field.
 *   - SPLIT_CASH rules -> split_account blocks (1-to-N and N-to-1).
 *   - Trigger-gated rules -> wrapped in `trigger_wrapper` blocks.
 *   - Bond, account, residual targets inside the rule's TARGETS slot.
 *   - Multi-group deals: rules are partitioned by `group_id`, each
 *     group rendered as its own top-level chain at a distinct x
 *     position so the canvas reads visually as "Group 1 stack | Group
 *     2 stack" without needing a new wrapper block type.
 *   - Cleanup rules (cap_mode=NONE) render the same as their
 *     scheduled counterparts; the cap_mode is preserved on each
 *     block's `data` field so the irGenerator can round-trip it.
 *
 * Round-trip preservation:
 *
 *   The PAC schedule_contract, Z accrual flags, relations,
 *   cap_mode, coverage_mode, kind, group_id, and other IR
 *   fields that don't have a corresponding visible Blockly field are
 *   stashed on each block's ``data`` field as JSON. When the user
 *   saves the deal back through ``irGenerator``, that helper reads
 *   the data field and merges those fields into the regenerated IR so
 *   PAC schedules and other economic fields are not lost on save.
 *
 *   Bond block data keys: kind, group_id, coupon_type, schedule_contract,
 *     relations (full payload including weights/leverage/cap/floor),
 *     z_accrual_enabled (explicit boolean).
 *   Rule block data keys: rule_id, group_id, cap_mode, coverage_mode,
 *     target_weights, extra_targets.
 */

// ---------------------------------------------------------------------------
// IR shape (a structural subset of DealDefinition; only the fields the
// synthesizer touches are typed here, so partial IR payloads from
// older deals don't trip the type-checker).
// ---------------------------------------------------------------------------

interface IRBond {
  name: string;
  kind?: string;
  coupon?: number | null;
  notional?: number;
  notional_pct_of_collateral?: number | null;
  pay_mode?: string;
  coupon_type?: string;
  index_name?: string | null;
  margin?: number | null;
  is_pseudo?: boolean;
  group_id?: string | null;
  schedule_contract?: Array<{ period: number; target_principal?: number; target_balance?: number }>;
  /** Machine-generated derivation provenance (PSA/CPR schedule inputs + method). */
  schedule_derivation?: Record<string, unknown> | null;
  /** Tolerance band in bps for PAC/TAC schedule enforcement. */
  schedule_tolerance_bps?: number | null;
  relations?: Array<{
    relation_type: string;
    targets: string[];
    weights?: number[] | null;
    leverage?: number | null;
    cap?: number | null;
    floor?: number | null;
    description?: string;
  }>;
  z_accrual_enabled?: boolean;
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
  group_id?: string | null;
  from_sources?: string[];
  to_targets?: string[];
  payment_style?: string;
  max_amount_fixed?: number | null;
  condition_trigger?: string | null;
  condition_invert?: boolean | null;
  target_weights?: number[] | null;
  cap_mode?: string | null;
  coverage_mode?: string | null;
}

interface IRGroup {
  group_id: string;
  label?: string;
}

export interface IRForSynthesis {
  bonds?: IRBond[];
  fees?: IRFee[];
  triggers?: IRTrigger[];
  waterfall_rules?: IRRule[];
  collateral_groups?: IRGroup[];
}

// ---------------------------------------------------------------------------
// Inverse mappings (IR canonical values -> Blockly UI dropdown values)
// ---------------------------------------------------------------------------

/** Inverse of `FEE_BASIS_MAP` in irGenerator: canonical -> UI value. */
const FEE_BASIS_INVERSE: Record<string, string> = {
  COLLATERAL_BALANCE: "PCT_POOL",
  FIXED_DOLLAR: "FIXED_DOLLAR",
  PER_LOAN: "PER_LOAN",
};

/** Inverse of `TRIGGER_METRIC_MAP`: canonical -> UI value. */
const TRIGGER_METRIC_INVERSE: Record<string, string> = {
  CUMULATIVE_LOSS: "CUM_LOSS",
  CUMULATIVE_DEFAULT: "CUM_DEFAULT",
  DELINQUENCY_RATE: "DELINQUENCY",
  OC_TEST: "OC_RATIO",
  IC_TEST: "IC_RATIO",
  CUSTOM: "CUSTOM",
};

/** Inverse of `PAY_TYPE_MAP`: canonical -> UI value. */
const PAY_TYPE_INVERSE: Record<string, string> = {
  PAY_INTEREST: "INTEREST",
  PAY_INTEREST_SHORTFALL: "INTEREST_SHORTFALL",
  PAY_PRINCIPAL: "PRINCIPAL",
  PAY_WRITEDOWN: "WRITEDOWN",
  PAY_RESIDUAL: "REMAINING",
};

/**
 * Group_<id>_<TOKEN> source tokens emitted by the multi-group runtime.
 * The synthesizer strips the prefix so the UI source dropdown reads
 * "Collection" / "Principal Collection" etc. (the runtime re-applies
 * the prefix at compile time when the rule has a group_id set).
 */
function _stripGroupPrefix(key: string): string {
  const m = /^GROUP_(.+?)_(CASH|ACT_INT|ACT_PRIN|COLLATERAL|LOSS)$/.exec(key);
  return m ? m[2] : key;
}

/**
 * Map a (possibly group-prefixed) source token back to the UI
 * dropdown value used by the source/account dropdowns. CASH ->
 * "COLLECTION" matches the irGenerator's `RULE_SOURCE_MAP` inverse.
 */
function ruleSourceForUI(source: string): string {
  const stripped = _stripGroupPrefix(source);
  if (stripped === "CASH") return "COLLECTION";
  if (stripped === "ACT_INT") return "INT_COLLECTION";
  if (stripped === "ACT_PRIN") return "PRIN_COLLECTION";
  // Legacy alias: old IRs that pre-date the BMA-native token rename
  // may carry a bare `COLLATERAL` token. Map it to the canonical CASH
  // dropdown value so legacy fixtures still round-trip correctly.
  if (stripped === "COLLATERAL") return "COLLECTION";
  return stripped;
}

// ---------------------------------------------------------------------------
// Blockly serialization-state types
// ---------------------------------------------------------------------------

interface BlocklyBlock {
  type: string;
  fields?: Record<string, string | number | boolean>;
  inputs?: Record<string, { block: BlocklyBlock }>;
  next?: { block: BlocklyBlock };
  /** Per-block free-form payload. Round-trips through serialize/deserialize.
   *  We use it to stash IR fields that have no native UI representation
   *  (cap_mode, kind, schedule_contract, relations,
   *  group_id, etc.) so a follow-up irGenerator pass can recover them. */
  data?: string;
  /** x/y are only set on top-level blocks. */
  x?: number;
  y?: number;
}

interface BlocklyWorkspaceState {
  blocks: {
    languageVersion: 0;
    blocks: BlocklyBlock[];
  };
}

// ---------------------------------------------------------------------------
// Public entry point
// ---------------------------------------------------------------------------

/**
 * Synthesize a Blockly workspace state from a deal IR. The result can
 * be passed to ``Blockly.serialization.workspaces.load(state, workspace)``.
 *
 * Multi-group deals get one top-level chain per group, laid out
 * horizontally. Single-group deals get one chain at the standard
 * (80, 60) origin. Returns null when there are no synthesizable
 * rules in any group (in which case the caller should leave the
 * canvas empty).
 */
export function synthesizeWorkspaceState(
  ir: IRForSynthesis,
): BlocklyWorkspaceState | null {
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
  const groups = ir.collateral_groups ?? [];
  const groupIds: (string | null)[] = groups.length > 0
    ? groups.map((g) => g.group_id)
    : [null];

  // Sort once globally; partition by group_id while preserving order.
  const allRules = (ir.waterfall_rules ?? [])
    .slice()
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

  const topLevelBlocks: BlocklyBlock[] = [];
  const X_STEP = 540;
  const Y_BASE = 60;
  let xOffset = 80;

  for (const groupId of groupIds) {
    const groupRules = allRules.filter((r) =>
      groupId === null
        ? !r.group_id
        : r.group_id === groupId,
    );
    if (groupRules.length === 0) continue;

    const grouped = _groupConsecutiveTriggers(groupRules);
    const ruleBlocks: BlocklyBlock[] = [];
    for (const item of grouped) {
      if (item.kind === "rule") {
        const blk = ruleToBlock(item.rule, bondByName, feeByName);
        if (blk) ruleBlocks.push(blk);
      } else {
        const trig = triggerByName.get(item.triggerName);
        if (!trig) continue;
        const inner = chainBlocks(
          item.rules
            .map((r) => ruleToBlock(r, bondByName, feeByName))
            .filter((b): b is BlocklyBlock => b !== null),
        );
        if (!inner) continue;
        ruleBlocks.push({
          type: "trigger_wrapper",
          fields: {
            TRIGGER_NAME: trig.name,
            METRIC: TRIGGER_METRIC_INVERSE[trig.metric_type] ?? "CUSTOM",
            THRESHOLD: trig.threshold_value,
          },
          inputs: {
            [item.invert ? "ELSE_RULES" : "RULES"]: { block: inner },
          },
        });
      }
    }
    const head = chainBlocks(ruleBlocks);
    if (!head) continue;
    head.x = xOffset;
    head.y = Y_BASE;
    if (groupId !== null) {
      // Stash group_id on the top of each chain so a future round-trip
      // (or visual hint) can find it. The blocks below in the chain
      // each carry their own `group_id` data too.
      _attachData(head, { group_id: groupId });
    }
    topLevelBlocks.push(head);
    xOffset += X_STEP;
  }

  if (topLevelBlocks.length === 0) return null;
  return { blocks: { languageVersion: 0, blocks: topLevelBlocks } };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

type RuleGroupItem =
  | { kind: "rule"; rule: IRRule }
  | { kind: "trigger"; triggerName: string; invert: boolean; rules: IRRule[] };

/**
 * Group consecutive rules that share a (trigger_name, invert) pair so
 * the synthesizer can emit a single trigger_wrapper around them. The
 * Blockly trigger block has THEN and ELSE statement slots; rules with
 * `condition_invert=true` go into the ELSE slot.
 */
function _groupConsecutiveTriggers(rules: IRRule[]): RuleGroupItem[] {
  const out: RuleGroupItem[] = [];
  for (const rule of rules) {
    const trig = rule.condition_trigger ?? null;
    if (!trig) {
      out.push({ kind: "rule", rule });
      continue;
    }
    const invert = !!rule.condition_invert;
    const last = out[out.length - 1];
    if (
      last
      && last.kind === "trigger"
      && last.triggerName === trig
      && last.invert === invert
    ) {
      last.rules.push(rule);
    } else {
      out.push({ kind: "trigger", triggerName: trig, invert, rules: [rule] });
    }
  }
  return out;
}

function _attachData(block: BlocklyBlock, data: Record<string, unknown>): void {
  let merged: Record<string, unknown> = {};
  if (block.data) {
    try {
      merged = JSON.parse(block.data) as Record<string, unknown>;
    } catch {
      merged = {};
    }
  }
  for (const [k, v] of Object.entries(data)) {
    if (v !== null && v !== undefined) merged[k] = v;
  }
  if (Object.keys(merged).length > 0) {
    block.data = JSON.stringify(merged);
  }
}

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

// ---------------------------------------------------------------------------
// Rule -> block dispatch
// ---------------------------------------------------------------------------

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
    case "PAY_INTEREST_SHORTFALL":
    case "PAY_WRITEDOWN":
    case "PAY_RESIDUAL":
      return waterfallRuleToBlock(rule, bondByName);
    case "SPLIT_CASH":
      return splitCashRuleToBlock(rule);
    default:
      // Unsupported rule types (PAY_PRINCIPAL_PAC_SCHEDULE,
      // PAY_PRINCIPAL_TAC_SCHEDULE, PAY_ACCRETION_REDIRECT) need
      // dedicated block types that carry their schedule metadata.
      // Synthesizing a placeholder pay_sequential block would lose
      // information; better to skip and let the user see the IR
      // tab for the missing rules until block coverage extends.
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
  // Inverse of irGenerator's `rate: amount / 100` for PCT_POOL fees:
  // rate=0.1 (decimal) -> amount=10 (annual bps display value).
  const amount = isPctPoolBps
    ? Math.round((fee?.rate ?? 0) * 100 * 100) / 100
    : (fee?.amount ?? 0);
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  const block: BlocklyBlock = {
    type: "pay_fee",
    fields: {
      PAYEE: payee,
      SOURCE: source,
      BASIS: basis,
      AMOUNT: amount,
      FREQ: fee?.frequency ?? "MONTHLY",
    },
  };
  _attachData(block, {
    rule_id: rule.rule_id,
    group_id: rule.group_id,
    cap_mode: rule.cap_mode,
    coverage_mode: rule.coverage_mode,
  });
  return block;
}

function waterfallRuleToBlock(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
): BlocklyBlock | null {
  const payType = PAY_TYPE_INVERSE[rule.rule_type] ?? "PRINCIPAL";
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  const targets = (rule.to_targets ?? []).map((name) =>
    targetToBlock(name, bondByName),
  );
  const targetChain = chainBlocks(
    targets.filter((t): t is BlocklyBlock => t !== null),
  );
  if (!targetChain) return null;

  const payment_style = rule.payment_style ?? "SEQUENTIAL";
  let block: BlocklyBlock;
  if (payment_style === "PRO_RATA") {
    block = {
      type: "pay_pro_rata",
      fields: {
        PAY_TYPE: payType,
        SOURCE: source,
        BASIS: "BALANCE",
        MAX_PAY: rule.max_amount_fixed ?? 0,
      },
      inputs: { TARGETS: { block: targetChain } },
    };
  } else {
    block = {
      type: "pay_sequential",
      fields: {
        PAY_TYPE: payType,
        SOURCE: source,
        // cap_mode=NONE rules ("cleanup" rules in FNR) don't have a
        // visible UI counterpart on the pay_sequential block, but we
        // can hint at their semantics via LIMIT="UNTIL_ZERO" (which
        // is the natural reading of "without regard to schedule").
        LIMIT: "UNTIL_ZERO",
        MAX_PAY: rule.max_amount_fixed ?? 0,
      },
      inputs: { TARGETS: { block: targetChain } },
    };
  }
  _attachData(block, {
    rule_id: rule.rule_id,
    group_id: rule.group_id,
    cap_mode: rule.cap_mode,
    coverage_mode: rule.coverage_mode,
  });
  return block;
}

function splitCashRuleToBlock(rule: IRRule): BlocklyBlock | null {
  const targets = rule.to_targets ?? [];
  if (targets.length === 0) return null;
  const source = ruleSourceForUI((rule.from_sources ?? ["CASH"])[0]);
  // The split_account block is a 2-output split. For 1->1 sweep-back
  // (target_weights=[1.0]) we still emit a split_account with the
  // second slot empty; for >2 targets we emit only the first two and
  // attach the rest on `data`.
  const block: BlocklyBlock = {
    type: "split_account",
    fields: {
      SOURCE: source,
      OUT_1: targets[0] ?? "",
      OUT_2: targets[1] ?? "",
    },
  };
  _attachData(block, {
    rule_id: rule.rule_id,
    group_id: rule.group_id,
    target_weights: rule.target_weights,
    extra_targets: targets.length > 2 ? targets.slice(2) : undefined,
  });
  return block;
}

// ---------------------------------------------------------------------------
// Target -> block dispatch
// ---------------------------------------------------------------------------

const RESIDUAL_TYPES = new Set(["RESIDUAL"]);
const ACCOUNT_LIKE_TARGETS = new Set([
  "WAWG_BUCKET", "PO_BUCKET", "ACT_INT", "ACT_PRIN", "CASH",
]);

function targetToBlock(
  name: string,
  bondByName: Map<string, IRBond>,
): BlocklyBlock | null {
  // Residual sweep targets ("R" or any explicit RESIDUAL bond) -> residual_target.
  if (name === "R") {
    const block: BlocklyBlock = {
      type: "residual_target",
      fields: { NAME: name, SHARE_PCT: 0 },
    };
    _attachData(block, { kind: "RESIDUAL" });
    return block;
  }
  const bond = bondByName.get(name);
  if (bond) {
    if (RESIDUAL_TYPES.has(bond.kind ?? "")) {
      const block: BlocklyBlock = {
        type: "residual_target",
        fields: { NAME: name, SHARE_PCT: 0 },
      };
      _attachData(block, _bondDataPayload(bond));
      return block;
    }
    return _bondTargetBlock(bond);
  }
  // Group-scoped sources like ACT_INT/ACT_PRIN and SPLIT_CASH virtual
  // streams (e.g. WAWG_BUCKET) aren't bond targets; render them as
  // account_target blocks so they have a place on the canvas. The
  // underlying IR distinction is preserved on the block's data field.
  if (ACCOUNT_LIKE_TARGETS.has(_stripGroupPrefix(name))) {
    return {
      type: "account_target",
      fields: {
        ACCOUNT_TYPE: name,
        INITIAL_MODE: "PCT_STACK",
        INITIAL_AMT: 0,
      },
    };
  }
  // Fallback: account-shaped target. Useful for fee names and any
  // unknown identifier so the chain doesn't break visually.
  return {
    type: "account_target",
    fields: {
      ACCOUNT_TYPE: name,
      INITIAL_MODE: "PCT_STACK",
      INITIAL_AMT: 0,
    },
  };
}

function _bondTargetBlock(bond: IRBond): BlocklyBlock {
  // Pseudo bonds (residual stub, fee-pay sinks) shouldn't reach here;
  // they're only valid inside dedicated residual_target blocks. We
  // route them through bond_target as a safety net but mark the data.
  const block: BlocklyBlock = {
    type: "bond_target",
    fields: {
      NAME: bond.name,
      BOND_TYPE: bond.coupon_type === "FLOATING" ? "FLOATING" : "FIXED",
      PAY_MODE: bond.pay_mode ?? "CASH_PAY",
      FACE_AMT: bond.notional ?? 0,
      SIZE_PCT_POOL: bond.notional_pct_of_collateral ?? 0,
      // Bonds with coupon_type=ZERO (PO classes) carry coupon=null in
      // the IR; show 0 in the UI so the field doesn't disappear.
      COUPON: bond.coupon ?? 0,
      INDEX_LABEL: "idx",
      INDEX_NAME: bond.index_name ?? "SOFR",
      SPREAD_LABEL: "sprd",
      MARGIN: bond.margin ?? 0,
      ACCRUAL: "30_360",
    },
  };
  _attachData(block, _bondDataPayload(bond));
  return block;
}

/**
 * Bundle the IR-level fields that don't have a native bond_target
 * field equivalent so a future round-trip can recover them.
 *
 * Specifically: `kind` (PAC/TAC/Z/IO/PO/etc),
 * `group_id`, the PAC `schedule_contract`, support relationships, Z
 * accrual flags, and notional-tracking pointers (IO classes).
 */
function _bondDataPayload(bond: IRBond): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  if (bond.kind) data.kind = bond.kind;
  if (bond.group_id) data.group_id = bond.group_id;
  if (bond.coupon_type) data.coupon_type = bond.coupon_type;
  if (bond.schedule_contract && bond.schedule_contract.length > 0) {
    data.schedule_contract = bond.schedule_contract;
  }
  // Stash machine-generated schedule provenance so it survives load/edit/save.
  if (bond.schedule_derivation != null) {
    data.schedule_derivation = bond.schedule_derivation;
  }
  // Stash user/machine tolerance so it is not reset to the default 25 bps on save.
  if (typeof bond.schedule_tolerance_bps === "number") {
    data.schedule_tolerance_bps = bond.schedule_tolerance_bps;
  }
  if (bond.relations && bond.relations.length > 0) data.relations = bond.relations;
  // Stash z_accrual_enabled as an explicit boolean (including false) so the
  // round-trip can distinguish "not-Z" (undefined) from "Z with accrual off".
  if (typeof bond.z_accrual_enabled === "boolean") {
    data.z_accrual_enabled = bond.z_accrual_enabled;
  }
  return data;
}

// ---------------------------------------------------------------------------
// Internal helper exported for tests (cashflow-stream conversion is the
// only piece of internal state that has independent test value).
// ---------------------------------------------------------------------------

export const _internals = {
  stripGroupPrefix: _stripGroupPrefix,
  ruleSourceForUI,
  groupConsecutiveTriggers: _groupConsecutiveTriggers,
};
