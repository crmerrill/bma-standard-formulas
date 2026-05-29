/**
 * Block color palette — Bloomberg Terminal inspired, dark/saturated.
 *
 * All colors have perceived brightness < 128 so Blockly uses WHITE text.
 * White text works on BOTH:
 *   (a) the colored block background
 *   (b) the dark field overlay (rgba black on the block color)
 * This is the only reliable approach — CSS overrides of Blockly's SVG
 * inline text fill are not portable across field types and renderers.
 *
 * Colors chosen to be visually distinct, rich, and professional —
 * inspired by Bloomberg's data-viz palette but adapted for dark canvas.
 */

// 16 dark, saturated, Bloomberg-inspired hues. All brightness < 128.
// brightness = (R*299 + G*587 + B*114) / 1000
const BOND_PALETTE = [
  "#B45309",  //  0: amber-700         brightness=103  warm gold
  "#1D4ED8",  //  1: blue-700          brightness=79   royal blue
  "#166534",  //  2: green-800         brightness=72   deep green
  "#9F1239",  //  3: rose-800          brightness=65   crimson
  "#5B21B6",  //  4: violet-800        brightness=67   deep purple
  "#0E7490",  //  5: cyan-700          brightness=73   teal/ocean
  "#854D0E",  //  6: yellow-800        brightness=85   dark gold
  "#9A3412",  //  7: orange-800        brightness=82   burnt orange
  "#1E40AF",  //  8: blue-800          brightness=70   navy
  "#3D6A16",  //  9: lime-800          brightness=82   olive green
  "#9D174D",  // 10: pink-800          brightness=72   magenta-rose
  "#115E59",  // 11: teal-800          brightness=56   dark seafoam
  "#78350F",  // 12: amber-900         brightness=74   dark bronze
  "#1E3A8A",  // 13: blue-900          brightness=57   deep navy
  "#831843",  // 14: pink-900          brightness=59   deep rose
  "#3B0764",  // 15: purple-950        brightness=23   ultra-deep purple
];

const ACCOUNT_PALETTE = [
  "#14532D",  // dark emerald
  "#166534",  // deep green
  "#15803D",  // green-700
  "#065F46",  // emerald-800
  "#064E3B",  // emerald-900
  "#134E4A",  // teal-900
];

const RESIDUAL_PALETTE = [
  "#78350F",  // amber-900 (gold)
  "#92400E",  // amber-800
  "#4C1D95",  // violet-900
  "#3B0764",  // purple-950
];

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

export function bondColor(_name: string, index: number): string {
  return BOND_PALETTE[index % BOND_PALETTE.length];
}

export function accountColor(_name: string, index: number): string {
  return ACCOUNT_PALETTE[index % ACCOUNT_PALETTE.length];
}

export function residualColor(name: string, _index: number): string {
  return RESIDUAL_PALETTE[hashName(name) % RESIDUAL_PALETTE.length];
}

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
    }
  }
}
