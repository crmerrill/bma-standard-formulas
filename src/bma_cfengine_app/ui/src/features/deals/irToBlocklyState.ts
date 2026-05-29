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
  description?: string;
}

/** Blockly v10 workspace-level comment (floating sticky note). */
interface BlocklyWorkspaceComment {
  text: string;
  pinned: boolean;
  height: number;
  width: number;
  x: number;
  y: number;
}

export interface IRForSynthesis {
  deal_name?: string;
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
  // Strip the GROUP_<id>_ prefix for grouped rules; the canonical name
  // is used directly as the field_input value (SOURCE is now field_input,
  // not field_dropdown, so any token name is valid).
  const stripped = _stripGroupPrefix(source);
  // Map legacy aliases to canonical names for backward compat.
  if (stripped === "COLLATERAL") return "CASH";
  // Canonical names (CASH, ACT_INT, ACT_PRIN, LOSS, bucket names, account
  // names, etc.) pass through verbatim — they're exactly what the analyst
  // should see in the SOURCE field_input.
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
  /** Workspace-level floating comments (Blockly v10 serialization). */
  comments?: BlocklyWorkspaceComment[];
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
/**
 * Build pay_accretion_redirect blocks for Z bonds in a group.
 *
 * The runtime handles Z accrual implicitly (via z_accrual_enabled flag and
 * ACCRETES_TO relations on the bond). To make this visible on the Blockly
 * canvas, the synthesizer injects an explicit accretion_redirect block so
 * the analyst can see which bonds receive the Z coupon as principal.
 *
 * Returns an array of blocks (one per Z bond with accrual enabled), or []
 * if no qualifying Z bonds are in this group.
 */
function _buildZAccretionRedirectBlocks(
  groupId: string | null,
  groupRules: IRRule[],
  bonds: IRBond[],
  bondByName: Map<string, IRBond>,
): BlocklyBlock[] {
  const blocks: BlocklyBlock[] = [];

  for (const bond of bonds) {
    // Only Z bonds with accrual enabled in the current group.
    if ((bond.kind ?? "") !== "Z") continue;
    if (!bond.z_accrual_enabled) continue;
    if (groupId !== null && bond.group_id !== groupId) continue;

    // Find the ACCRETES_TO relation targets.
    const accretesTo: string[] = [];
    for (const rel of bond.relations ?? []) {
      if ((rel as Record<string, unknown>).relation_type === "ACCRETES_TO") {
        const targets = (rel as Record<string, unknown>).targets as string[] | undefined;
        if (Array.isArray(targets)) accretesTo.push(...targets);
      }
    }
    if (accretesTo.length === 0) continue;

    // Build bond_target blocks for the ACCRETES_TO targets.
    const targetChain = chainBlocks(
      accretesTo
        .map((n) => targetToBlock(n, bondByName))
        .filter((b): b is BlocklyBlock => b !== null),
    );
    if (!targetChain) continue;

    const block: BlocklyBlock = {
      type: "pay_accretion_redirect",
      fields: {
        Z_TRANCHE: bond.name,
        SOURCE: "ACT_PRIN",
        MAX_PAY: 0,
      },
      inputs: { TARGETS: { block: targetChain } },
    };
    _attachData(block, { group_id: bond.group_id ?? groupId ?? undefined });
    blocks.push(block);
  }

  return blocks;
}

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

  const groupByGroupId = new Map<string, IRGroup>();
  for (const g of groups) {
    if (g?.group_id) groupByGroupId.set(g.group_id, g);
  }

  const topLevelBlocks: BlocklyBlock[] = [];
  const workspaceComments: BlocklyWorkspaceComment[] = [];
  const X_STEP = 540;
  const Y_BASE = 80;  // pushed down to make room for the group label comment
  const COMMENT_Y = 12;
  const COMMENT_HEIGHT = 46;
  const COMMENT_WIDTH = 480;
  let xOffset = 80;
  const isMultiGroup = groups.length > 1;

  for (const groupId of groupIds) {
    const groupRules = allRules.filter((r) =>
      groupId === null
        ? !r.group_id
        : r.group_id === groupId,
    );
    if (groupRules.length === 0) continue;

    // OA-Z: If the group contains a Z bond with z_accrual_enabled + ACCRETES_TO,
    // inject a pay_accretion_redirect block after the last PAC rule that targets
    // the Z's accretion targets. This makes the Z accrual mechanic explicit on the
    // canvas — without it the analyst can't see where the Z coupon is redirected.
    const zRedirectBlocks: BlocklyBlock[] = _buildZAccretionRedirectBlocks(
      groupId,
      groupRules,
      ir.bonds ?? [],
      bondByName,
    );

    const grouped = _groupConsecutiveTriggers(groupRules);
    const ruleBlocks: BlocklyBlock[] = [];
    for (const item of grouped) {
      if (item.kind === "rule") {
        const blk = ruleToBlock(item.rule, bondByName, feeByName);
        if (blk) ruleBlocks.push(blk);
        // Insert Z accretion redirect blocks immediately after the last rule
        // that targets the ACCRETES_TO bonds (usually PAC II principal rule).
        if (
          zRedirectBlocks.length > 0 &&
          item.rule.rule_type === "PAY_PRINCIPAL" &&
          !item.rule.cap_mode &&
          (item.rule.to_targets ?? []).some((t) => {
            const b = bondByName.get(t);
            return b && b.kind === "PAC";
          })
        ) {
          // Check this is the last PAC rule before Z (look ahead for Z target)
          const thisOrder = item.rule.order ?? 0;
          const nextRuleHasZ = groupRules.some(
            (r) =>
              (r.order ?? 0) > thisOrder &&
              (r.to_targets ?? []).some((t) => {
                const b = bondByName.get(t);
                return b?.kind === "Z";
              }),
          );
          if (nextRuleHasZ) {
            for (const zb of zRedirectBlocks) ruleBlocks.push(zb);
            // Clear so we only inject once
            zRedirectBlocks.length = 0;
          }
        }
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
      _attachData(head, { group_id: groupId });
    }
    topLevelBlocks.push(head);

    // Add a floating label comment above each group column so the analyst
    // knows which collateral pool the waterfall applies to.
    if (isMultiGroup && groupId !== null) {
      const groupMeta = groupByGroupId.get(groupId);
      // Prefer the explicit label, fall back to the group_id, strip "GROUP_" prefix
      // for readability ("GROUP_1" → "Group 1").
      const displayId = (groupMeta?.label || groupId)
        .replace(/^GROUP_/i, "Group ");
      const desc = groupMeta?.description ? `\n${groupMeta.description}` : "";
      workspaceComments.push({
        text: `📦 ${displayId} — Collateral Pool Waterfall${desc}`,
        pinned: false,
        height: COMMENT_HEIGHT + (desc ? 16 : 0),
        width: COMMENT_WIDTH,
        x: xOffset,
        y: COMMENT_Y,
      });
    } else if (!isMultiGroup) {
      // Single-pool deal: show a compact identifier above the single column.
      const dealName = (ir as Record<string, unknown>).deal_name as string | undefined;
      if (dealName) {
        workspaceComments.push({
          text: `📦 ${dealName} — Priority of Payments`,
          pinned: false,
          height: COMMENT_HEIGHT - 8,
          width: COMMENT_WIDTH,
          x: xOffset,
          y: COMMENT_Y,
        });
      }
    }

    xOffset += X_STEP;
  }

  if (topLevelBlocks.length === 0) return null;
  const state: BlocklyWorkspaceState = { blocks: { languageVersion: 0, blocks: topLevelBlocks } };
  if (workspaceComments.length > 0) state.comments = workspaceComments;
  return state;
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
    case "PAY_PRINCIPAL_PAC_SCHEDULE":
      // Legacy explicit PAC schedule rule type — synthesize as pay_pac_schedule block.
      return _pacTacRuleToBlock(rule, bondByName, "PAC");
    case "PAY_PRINCIPAL_TAC_SCHEDULE":
      // Legacy explicit TAC schedule rule type.
      return _pacTacRuleToBlock(rule, bondByName, "TAC");
    default:
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

/**
 * Detect whether a PAY_PRINCIPAL rule should be synthesized as a PAC or TAC
 * schedule block instead of a plain pay_sequential block.
 *
 * A rule is "pac-like" when:
 *   - rule_type = PAY_PRINCIPAL
 *   - cap_mode is null / "PLANNED" / "SCHEDULED" / "TARGETED" (not NONE — NONE
 *     is the cleanup pattern which should stay as pay_sequential)
 *   - ALL non-residual targets are PAC bonds (kind=PAC) with a schedule_contract
 *
 * Same check for TAC (kind=TAC).
 */
function _detectPacTacRule(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
): "PAC" | "TAC" | null {
  if (rule.rule_type !== "PAY_PRINCIPAL") return null;
  // NONE cap_mode = cleanup rule, keep as pay_sequential.
  if (rule.cap_mode === "NONE") return null;

  const targets = (rule.to_targets ?? []).filter((n) => bondByName.has(n));
  if (targets.length === 0) return null;

  const kinds = new Set(targets.map((n) => bondByName.get(n)?.kind ?? "CASH_PAY"));
  const hasContract = targets.every((n) => (bondByName.get(n)?.schedule_contract ?? []).length > 0);

  if (!hasContract) return null;
  if (kinds.size === 1 && kinds.has("PAC")) return "PAC";
  if (kinds.size === 1 && kinds.has("TAC")) return "TAC";
  return null;
}

function waterfallRuleToBlock(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
): BlocklyBlock | null {
  // Attempt PAC/TAC schedule block synthesis before falling through to generic.
  const pacKind = _detectPacTacRule(rule, bondByName);
  if (pacKind) {
    return _pacTacRuleToBlock(rule, bondByName, pacKind);
  }

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
        // cap_mode=NONE rules ("cleanup" rules) are the "without regard to
        // schedule" cleanup pattern.
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
    // Stash the canonical from_sources so that custom bucket names
    // (e.g. WAWG_BUCKET, PO_BUCKET) survive the round-trip even when
    // the SOURCE dropdown falls back to "COLLECTION" for unknown values.
    canonical_source: (rule.from_sources ?? []).join(",") || undefined,
  });
  return block;
}

/**
 * Synthesize a pay_pac_schedule or pay_tac_schedule block from a PAY_PRINCIPAL
 * rule whose targets are all PAC or TAC bonds.
 *
 * Model parameters (speed_low, speed_high, model_type) are read from the FIRST
 * target bond.  When not set (schedule derived from prospectus tables), we use
 * model_type=CUSTOM_VECTOR so the block accurately signals the derivation method.
 *
 * Support bonds come from the first target bond's SUPPORTED_BY relations and are
 * chained into the SUPPORT_BONDS statement slot.
 */
function _pacTacRuleToBlock(
  rule: IRRule,
  bondByName: Map<string, IRBond>,
  pacKind: "PAC" | "TAC",
): BlocklyBlock | null {
  const source = ruleSourceForUI((rule.from_sources ?? ["ACT_PRIN"])[0]);

  // Representative bond for model parameters.
  const firstTarget = (rule.to_targets ?? [])[0];
  const repBond = firstTarget ? bondByName.get(firstTarget) : undefined;
  const modelType = (repBond?.schedule_model_type as string | null | undefined)
    ?? "CUSTOM_VECTOR";
  const speedLow = repBond?.schedule_speed_low ?? 0;
  const speedHigh = repBond?.schedule_speed_high ?? 0;
  const priorityTier = repBond?.schedule_priority_tier ?? 1;
  const dependsOn = repBond?.schedule_depends_on ?? "";

  // Target bond blocks.
  const targetChain = chainBlocks(
    (rule.to_targets ?? [])
      .map((n) => targetToBlock(n, bondByName))
      .filter((b): b is BlocklyBlock => b !== null),
  );
  if (!targetChain) return null;

  // Support bonds come from SUPPORTED_BY relations on the first target bond.
  const supportNames: string[] = [];
  if (repBond?.relations) {
    for (const rel of repBond.relations) {
      if ((rel as Record<string, unknown>).relation_type === "SUPPORTED_BY") {
        const relTargets = (rel as Record<string, unknown>).targets as string[] | undefined;
        if (Array.isArray(relTargets)) supportNames.push(...relTargets);
      }
    }
  }
  const supportChain = chainBlocks(
    supportNames
      .map((n) => targetToBlock(n, bondByName))
      .filter((b): b is BlocklyBlock => b !== null),
  );

  const blockType = pacKind === "PAC" ? "pay_pac_schedule" : "pay_tac_schedule";
  const block: BlocklyBlock = {
    type: blockType,
    fields: {
      MODEL_TYPE: modelType,
      SPEED_LOW: speedLow,
      SPEED_HIGH: speedHigh,
      CUSTOM_VECTOR: "",     // contract lives in bond block.data, not here
      SOURCE: source,
      PRIORITY_TIER: priorityTier,
      DEPENDS_ON: dependsOn,
    },
    inputs: {
      TARGETS: { block: targetChain },
      ...(supportChain ? { SUPPORT_BONDS: { block: supportChain } } : {}),
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
    // Multi-source SPLIT_CASH (N→1 sweep-back): stash extra sources so the
    // round-trip can recover them (the SOURCE field only holds sources[0]).
    extra_sources: (rule.from_sources ?? []).length > 1 ? (rule.from_sources ?? []).slice(1) : undefined,
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
  // Stash schedule parameters so load→Blockly→save is lossless for PAC/TAC bonds.
  // These live on the PAC rule block when the user edits live; but when a saved IR
  // is loaded via irToBlocklyState (no PAC block created), they must survive via
  // bond_target block.data so irGenerator can emit the correct values.
  if (bond.schedule_model_type != null) data.schedule_model_type = bond.schedule_model_type;
  if (bond.schedule_speed_low != null) data.schedule_speed_low = bond.schedule_speed_low;
  if (bond.schedule_speed_high != null) data.schedule_speed_high = bond.schedule_speed_high;
  if (bond.schedule_priority_tier != null) data.schedule_priority_tier = bond.schedule_priority_tier;
  if (bond.schedule_depends_on != null) data.schedule_depends_on = bond.schedule_depends_on;
  if (bond.schedule_custom_vector != null) data.schedule_custom_vector = bond.schedule_custom_vector;
  // Stash machine-generated schedule provenance so it survives load/edit/save.
  if (bond.schedule_derivation != null) {
    data.schedule_derivation = bond.schedule_derivation;
  }
  if (typeof bond.schedule_tolerance_bps === "number") {
    data.schedule_tolerance_bps = bond.schedule_tolerance_bps;
  }
  // Stash non-scalar coupon/margin/cap/floor schedules (RateOrSchedule) so they
  // survive load→edit→save without collapsing to the block's scalar COUPON field.
  if (Array.isArray((bond as Record<string, unknown>).coupon)) {
    data.coupon_schedule = (bond as Record<string, unknown>).coupon;
  }
  if (Array.isArray((bond as Record<string, unknown>).margin)) {
    data.margin_schedule = (bond as Record<string, unknown>).margin;
  }
  if (Array.isArray((bond as Record<string, unknown>).cap)) {
    data.cap_schedule = (bond as Record<string, unknown>).cap;
  }
  if (Array.isArray((bond as Record<string, unknown>).floor_rate)) {
    data.floor_schedule = (bond as Record<string, unknown>).floor_rate;
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
