/**
 * Bloomberg-inspired block color palettes for the Structuring Studio.
 *
 * Design principles:
 *   1. Curated fixed palette — deliberate, professional, not random-looking.
 *      Inspired by Bloomberg Terminal's saturated chart-series colors.
 *   2. All colors have perceived brightness ≥ 150 so Blockly always picks
 *      BLACK text. Black text is readable on both colored block backgrounds
 *      AND inside the white field_input boxes.
 *   3. Bond colors: 16 maximally distinct hues, each hand-selected to look
 *      intentional and distinguishable at a glance.
 *   4. Accounts: green family. Residuals: gold family.
 *      Pay rules keep their dark static colors (structure layer).
 */

// ---------------------------------------------------------------------------
// Bloomberg-inspired bond color palette — 16 curated colors
// Each verified: perceived brightness = (R*299 + G*587 + B*114)/1000 >= 150
// ---------------------------------------------------------------------------
const BOND_PALETTE = [
  "#F5A623",  //  0: Bloomberg amber (signature orange)
  "#4DB6FF",  //  1: sky blue
  "#57D68D",  //  2: mint green
  "#FF7676",  //  3: salmon / coral red
  "#B39DFF",  //  4: lavender / soft purple
  "#26D8F8",  //  5: cyan / electric blue
  "#FFE14D",  //  6: golden yellow
  "#FF9A56",  //  7: peach / warm orange
  "#7B9FFF",  //  8: periwinkle
  "#A8E063",  //  9: lime green
  "#FF8AC4",  // 10: hot pink
  "#4ECDC4",  // 11: teal / seafoam
  "#C8A87E",  // 12: warm tan / gold
  "#73C7E4",  // 13: steel blue
  "#FF6CAB",  // 14: deep pink
  "#A3E635",  // 15: chartreuse
];

// Account palette: greens family
const ACCOUNT_PALETTE = [
  "#6EE7B7",  //  0: emerald
  "#34D399",  //  1: green-teal
  "#A7F3D0",  //  2: light mint
  "#86EFAC",  //  3: sage
  "#4ADE80",  //  4: bright green
  "#BBF7D0",  //  5: pale green
];

// Residual palette: gold / purple family (equity / remainder feel)
const RESIDUAL_PALETTE = [
  "#FDE68A",  //  0: golden yellow
  "#FCD34D",  //  1: amber
  "#DDD6FE",  //  2: lavender
  "#C4B5FD",  //  3: purple
];

// ---------------------------------------------------------------------------
// Color functions
// ---------------------------------------------------------------------------

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

/**
 * Bond colors — indexed from the curated Bloomberg palette.
 * Same bond name always gets the same color (index → color).
 * Hash provides tie-breaking within the same index slot (minor hue shift
 * for names that alias to the same index mod palette-size).
 */
export function bondColor(name: string, index: number): string {
  // Primary: rotate through the curated palette by index.
  const paletteIdx = index % BOND_PALETTE.length;
  return BOND_PALETTE[paletteIdx];
}

/**
 * Account colors — greens family, index-driven.
 */
export function accountColor(name: string, index: number): string {
  return ACCOUNT_PALETTE[index % ACCOUNT_PALETTE.length];
}

/**
 * Residual colors — gold / purple family.
 */
export function residualColor(name: string, _index: number): string {
  // Most deals have one residual; use hash to pick from the residual palette.
  const h = hashName(name);
  return RESIDUAL_PALETTE[h % RESIDUAL_PALETTE.length];
}

/**
 * Apply dynamic colors to all target blocks in the workspace.
 * Pay rules, fees, and splits keep their static colors from block definitions.
 */
export function applyDynamicColors(workspace: any): void {
  if (!workspace) return;

  const allBlocks = workspace.getAllBlocks(false);

  const bondNames: string[] = [];
  const accountNames: string[] = [];
  const residualNames: string[] = [];

  for (const block of allBlocks) {
    if (block.type === "bond_target") {
      const name = block.getFieldValue("NAME");
      if (name && !bondNames.includes(name)) bondNames.push(name);
    } else if (block.type === "account_target") {
      const name = block.getFieldValue("ACCOUNT_TYPE");
      if (name && !accountNames.includes(name)) accountNames.push(name);
    } else if (block.type === "residual_target") {
      const name = block.getFieldValue("NAME");
      if (name && !residualNames.includes(name)) residualNames.push(name);
    }
  }

  for (const block of allBlocks) {
    switch (block.type) {
      case "bond_target": {
        const name = block.getFieldValue("NAME");
        const idx = bondNames.indexOf(name);
        if (idx >= 0) block.setColour(bondColor(name, idx));
        break;
      }
      case "account_target": {
        const name = block.getFieldValue("ACCOUNT_TYPE");
        const idx = accountNames.indexOf(name);
        if (idx >= 0) block.setColour(accountColor(name, idx));
        break;
      }
      case "residual_target": {
        const name = block.getFieldValue("NAME");
        const idx = residualNames.indexOf(name);
        if (idx >= 0) block.setColour(residualColor(name, idx));
        break;
      }
      default:
        break;
    }
  }
}
