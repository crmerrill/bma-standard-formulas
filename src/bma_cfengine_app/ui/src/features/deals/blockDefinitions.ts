/**
 * Blockly block definitions — clean waterfall with inline properties.
 *
 * No Deal block. No separate bond/account definition blocks.
 * Pay rules are the primary blocks. Targets snap inside with full properties.
 * Source account is a dropdown on the rule.
 * Property panel syncs edits across all targets with the same name.
 */

const ACCRUAL_OPTIONS: [string, string][] = [
  ["30/360", "30_360"],
  ["ACT/360", "ACT_360"],
  ["ACT/365", "ACT_365"],
  ["ACT/ACT", "ACT_ACT"],
];

const ACCOUNT_SOURCE_OPTIONS: [string, string][] = [
  ["Collection", "COLLECTION"],
  ["Principal Collection", "PRIN_COLLECTION"],
  ["Interest Collection", "INT_COLLECTION"],
  ["Distribution", "DISTRIBUTION"],
  ["Reserve", "RESERVE"],
  ["Prefunding", "PREFUNDING"],
  ["Capitalized Interest", "CAP_INTEREST"],
  ["Expense", "EXPENSE"],
  ["Reinvestment", "REINVESTMENT"],
  ["Swap / Hedge", "SWAP_HEDGE"],
  ["Escrow", "ESCROW"],
  ["Yield Supplement", "YIELD_SUPPLEMENT"],
];

const PAYMENT_TYPE_OPTIONS: [string, string][] = [
  ["Interest", "INTEREST"],
  ["Interest Shortfall", "INTEREST_SHORTFALL"],
  ["Principal", "PRINCIPAL"],
  ["Priority Principal", "PRIORITY_PRINCIPAL"],
  ["Writedown", "WRITEDOWN"],
  ["Loss Recovery", "LOSS_RECOVERY"],
  ["Remaining Funds", "REMAINING"],
];

const LIMIT_OPTIONS: [string, string][] = [
  ["None", "NONE"],
  ["Until bal = 0", "UNTIL_ZERO"],
  ["Cap amount", "CAP"],
  ["Until trigger", "UNTIL_TRIGGER"],
];

const FEE_PAYEE_OPTIONS: [string, string][] = [
  ["Servicer", "SERVICER"],
  ["Trustee", "TRUSTEE"],
  ["Owner", "OWNER"],
  ["Admin", "ADMIN"],
  ["Backup Servicer", "BACKUP_SERVICER"],
  ["Custodian", "CUSTODIAN"],
  ["Asset Rep Reviewer", "ASSET_REP_REVIEWER"],
  ["Other", "OTHER"],
];

const FEE_BASIS_OPTIONS: [string, string][] = [
  ["bps of pool bal", "PCT_POOL"],
  ["Fixed $", "FIXED_DOLLAR"],
  ["Per loan $", "PER_LOAN"],
];

const ACCOUNT_INITIAL_MODE: [string, string][] = [
  ["% bond stack", "PCT_STACK"],
  ["$ amount", "FIXED_DOLLAR"],
];

const BOND_TYPE_OPTIONS: [string, string][] = [
  ["Fixed", "FIXED"],
  ["Floating", "FLOATING"],
];

const INDEX_OPTIONS: [string, string][] = [
  ["SOFR", "SOFR"],
  ["Term SOFR 1M", "TERM_SOFR_1M"],
  ["Term SOFR 3M", "TERM_SOFR_3M"],
  ["CMT 1Y", "CMT_1Y"],
  ["Prime", "PRIME"],
  ["Other", "OTHER"],
];

export const DEAL_BLOCKS = [

  // =================================================================
  // PAY RULES (primary blocks — the waterfall)
  // =================================================================

  {
    type: "pay_sequential",
    message0: "Pay Sequential %1 from %2 %3 limit %4 max pay $%5 %6 targets: %7",
    args0: [
      { type: "field_dropdown", name: "PAY_TYPE", options: PAYMENT_TYPE_OPTIONS },
      { type: "field_dropdown", name: "SOURCE", options: ACCOUNT_SOURCE_OPTIONS },
      { type: "input_dummy" },
      { type: "field_dropdown", name: "LIMIT", options: LIMIT_OPTIONS },
      { type: "field_number", name: "MAX_PAY", value: 0, min: 0, precision: 1 },
      { type: "input_dummy" },
      { type: "input_statement", name: "TARGETS", check: "target_item" },
    ],
    previousStatement: "waterfall_item",
    nextStatement: "waterfall_item",
    colour: "#1e3a6b",
    tooltip:
      "Pay targets sequentially. Max pay $ caps the first target in this step (0 = no cap).",
  },

  {
    type: "pay_pro_rata",
    message0: "Pay Pro Rata %1 from %2 %3 by %4 max pay $%5 %6 targets: %7",
    args0: [
      { type: "field_dropdown", name: "PAY_TYPE", options: PAYMENT_TYPE_OPTIONS },
      { type: "field_dropdown", name: "SOURCE", options: ACCOUNT_SOURCE_OPTIONS },
      { type: "input_dummy" },
      { type: "field_dropdown", name: "BASIS", options: [["Balance", "BALANCE"], ["Face", "FACE"], ["Equal", "EQUAL"]] },
      { type: "field_number", name: "MAX_PAY", value: 0, min: 0, precision: 1 },
      { type: "input_dummy" },
      { type: "input_statement", name: "TARGETS", check: "target_item" },
    ],
    previousStatement: "waterfall_item",
    nextStatement: "waterfall_item",
    colour: "#0e7490",
    tooltip:
      "Pay pro rata to all targets in one step. Max pay $ caps total for this rule (0 = no cap).",
  },

  {
    type: "pay_fee",
    message0: "Pay Fee %1 from %2 %3 %4",
    args0: [
      { type: "field_dropdown", name: "PAYEE", options: FEE_PAYEE_OPTIONS },
      { type: "field_dropdown", name: "SOURCE", options: ACCOUNT_SOURCE_OPTIONS },
      { type: "field_dropdown", name: "BASIS", options: FEE_BASIS_OPTIONS },
      { type: "field_number", name: "AMOUNT", value: 0, min: 0, precision: 0.01 },
    ],
    previousStatement: "waterfall_item",
    nextStatement: "waterfall_item",
    colour: "#1d4ed8",
    tooltip:
      "Fee to payee. For “bps of pool bal”, enter basis points (25 = 0.25%). Fixed $ and per loan use dollars.",
  },

  {
    type: "split_account",
    message0: "Split %1 into %2 and %3",
    args0: [
      { type: "field_dropdown", name: "SOURCE", options: ACCOUNT_SOURCE_OPTIONS },
      { type: "field_input", name: "OUT_1", text: "Principal Collection" },
      { type: "field_input", name: "OUT_2", text: "Interest Collection" },
    ],
    previousStatement: "waterfall_item",
    nextStatement: "waterfall_item",
    colour: "#334155",
    tooltip: "Split an account into two sub-accounts (e.g., P/I split).",
  },

  // =================================================================
  // TARGETS (snap inside pay rules)
  // =================================================================

  // Bond target — full properties inline, synced by name via property panel
  {
    type: "bond_target",
    message0: "→ %1 %2 face $%3 cpn %4%% %5",
    args0: [
      { type: "field_input", name: "NAME", text: "A" },
      { type: "field_dropdown", name: "BOND_TYPE", options: BOND_TYPE_OPTIONS },
      { type: "field_number", name: "FACE_AMT", value: 70000000, min: 0, precision: 1 },
      { type: "field_number", name: "COUPON", value: 5.0, min: 0, precision: 0.01 },
      { type: "field_dropdown", name: "ACCRUAL", options: ACCRUAL_OPTIONS },
    ],
    previousStatement: "target_item",
    nextStatement: "target_item",
    colour: "#dc2626",
    tooltip:
      "Bond target. Face in dollars. Red/orange hues vary by tranche name (property panel syncs names).",
  },

  // Account target — initial balance as % of bond stack or fixed $
  {
    type: "account_target",
    message0: "→ %1 init %2 %3",
    args0: [
      { type: "field_dropdown", name: "ACCOUNT_TYPE", options: ACCOUNT_SOURCE_OPTIONS },
      { type: "field_dropdown", name: "INITIAL_MODE", options: ACCOUNT_INITIAL_MODE },
      { type: "field_number", name: "INITIAL_AMT", value: 0, min: 0, precision: 0.01 },
    ],
    previousStatement: "target_item",
    nextStatement: "target_item",
    colour: "#16a34a",
    tooltip:
      "Account receiving cash. Init: % bond stack = percent of total bond face; $ amount = fixed starting balance. Greens vary by account.",
  },

  // Residual target — simplest target, just a name, no face/coupon
  {
    type: "residual_target",
    message0: "→ %1 (residual)",
    args0: [
      { type: "field_input", name: "NAME", text: "R" },
    ],
    previousStatement: "target_item",
    nextStatement: "target_item",
    colour: "#7c3aed",
    tooltip: "Residual — remaining funds. Purple family varies by name.",
  },

  // =================================================================
  // WRAPPERS
  // =================================================================

  {
    type: "trigger_wrapper",
    message0: "IF %1 %2 > %3 %4",
    args0: [
      { type: "field_input", name: "TRIGGER_NAME", text: "CumLoss" },
      { type: "field_dropdown", name: "METRIC", options: [
        ["Cum Loss", "CUM_LOSS"],
        ["Cum Default", "CUM_DEFAULT"],
        ["OC Ratio", "OC_RATIO"],
        ["IC Ratio", "IC_RATIO"],
        ["Delinquency", "DELINQUENCY"],
        ["Custom", "CUSTOM"],
      ]},
      { type: "field_number", name: "THRESHOLD", value: 0.05, min: 0, precision: 0.001 },
      { type: "input_dummy" },
    ],
    message1: "then %1",
    args1: [
      { type: "input_statement", name: "RULES", check: "waterfall_item" },
    ],
    message2: "else %1",
    args2: [
      { type: "input_statement", name: "ELSE_RULES", check: "waterfall_item" },
    ],
    previousStatement: "waterfall_item",
    nextStatement: "waterfall_item",
    colour: "#92400e",
    tooltip:
      "THEN: pay rules while metric > threshold (trigger on). ELSE: pay rules when not. Matches runtime condition_invert.",
  },
];

// No reference block factories needed — targets carry their own properties
// and are synced by name via the property panel component
