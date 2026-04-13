/**
 * Blockly toolbox — clean waterfall-first layout.
 *
 * No Deal block. No separate definition categories.
 * Just: Pay Rules, Targets, Triggers.
 */

const CAT = "#64748b";

export const TOOLBOX_CONFIG = {
  kind: "categoryToolbox",
  contents: [
    {
      kind: "category",
      name: "Pay Rules",
      colour: CAT,
      contents: [
        { kind: "block", type: "pay_sequential" },
        { kind: "block", type: "pay_pro_rata" },
        { kind: "block", type: "pay_pac_schedule" },
        { kind: "block", type: "pay_tac_schedule" },
        { kind: "block", type: "pay_accretion_redirect" },
      { kind: "block", type: "pay_fee" },
      { kind: "block", type: "split_account" },
      ],
    },
    {
      kind: "category",
      name: "Targets",
      colour: CAT,
      contents: [
      { kind: "block", type: "bond_target" },
      { kind: "block", type: "account_target" },
      { kind: "block", type: "residual_target" },
      ],
    },
    {
      kind: "category",
      name: "Triggers",
      colour: CAT,
      contents: [
        { kind: "block", type: "trigger_wrapper" },
      ],
    },
  ],
};

export function buildToolbox() {
  return TOOLBOX_CONFIG;
}
