/**
 * Dynamic colors for target blocks only.
 *
 * Pay rules keep their static blues / blue-greens from block definitions.
 * Targets use saturated, well-separated hues so tranches are scannable.
 *
 * Design rules:
 *   1. LIGHTNESS ≤ 44% everywhere — keeps Blockly's automatic text color WHITE.
 *      Above ~50% lightness Blockly switches to black text, which is nearly
 *      invisible on a dark canvas. Hard cap at 44%.
 *   2. Bond hues use a GOLDEN-RATIO SPREAD (137.5°/step) across the usable arc,
 *      skipping green/teal (100-200°) and violet (250-320°) which belong to
 *      accounts and residuals. This gives 15+ bonds fully distinct colors with
 *      no repeats before the sequence wraps.
 *   3. Accounts stay in greens (108-165°), residuals in violet-purple (258-320°).
 */

function hashName(name: string): number {
  let h = 0;
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) - h + name.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
}

function hslToHex(h: number, s: number, l: number): string {
  h = ((h % 360) + 360) % 360;
  s = Math.max(0, Math.min(100, s));
  // Lightness range 48-60%: keeps Blockly's perceived brightness ≥ 128 so
  // it renders BLACK text.  Black text is readable BOTH on the pastel block
  // background AND inside the white field_input / field_number boxes.
  // (Capping at ≤ 44% forced white text, which was invisible inside white fields.)
  l = Math.max(48, Math.min(60, l));

  const s1 = s / 100;
  const l1 = l / 100;
  const a = s1 * Math.min(l1, 1 - l1);
  const f = (n: number) => {
    const k = (n + h / 30) % 12;
    const color = l1 - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
    return Math.round(255 * color).toString(16).padStart(2, "0");
  };
  return `#${f(0)}${f(8)}${f(4)}`;
}

/**
 * Bonds — golden-ratio hue spread (137.5°/step) remapped to avoid the green/teal
 * (100-200°) and violet (250-320°) arcs used by accounts and residuals.
 * With 15 bonds this produces 15 fully distinct, readable colors before any wrap.
 */
export function bondColor(name: string, index: number): string {
  const h = hashName(name);
  // Golden angle (137.5°) gives maximum perceptual separation at each step.
  const rawHue = (index * 137.508) % 360;

  // Remap to skip green/teal (100-200°) and violet (250-320°):
  //   0-99   → kept as-is (red, orange, yellow)
  //   100-249 → compressed to 205-249 (blue/indigo/cyan-dark)
  //   250-359 → shifted to 320-359 (magenta/rose/hot-pink)
  let hue: number;
  if (rawHue < 100) {
    hue = rawHue;
  } else if (rawHue < 250) {
    hue = 205 + ((rawHue - 100) / 150) * 44;
  } else {
    hue = 320 + ((rawHue - 250) / 110) * 39;
  }

  // Small per-name variation (±4°) so identically-indexed bonds with similar
  // names still visibly differ (e.g. PA vs PB in adjacent slots).
  hue = (hue + (h % 9) - 4 + 360) % 360;

  const sat = 55 + (h % 18);   // 55-72: saturated but not garish at lighter L
  const light = 50 + (h % 10); // 50-59: inside 48-60 clamp → black text always
  return hslToHex(hue, sat, light);
}

/**
 * Accounts — greens (108-165°), clearly separated from bonds and residuals.
 */
export function accountColor(name: string, index: number): string {
  const h = hashName(name) + index * 5003;
  const hue = 108 + ((index * 23 + (h % 11)) % 58); // 108-165
  const sat = 50 + ((h >>> 2) % 20);   // 50-69
  const light = 50 + ((h >>> 6) % 10); // 50-59 → black text
  return hslToHex(hue, sat, light);
}

/** Residuals — violet / purple (258-320°) */
export function residualColor(name: string, index: number): string {
  const h = hashName(name) + index * 3001;
  const hue = 258 + ((index * 19 + (h % 13)) % 62); // 258-319
  const sat = 50 + ((h >>> 2) % 20);   // 50-69
  const light = 50 + ((h >>> 6) % 10); // 50-59 → black text
  return hslToHex(hue, sat, light);
}

/**
 * Target blocks only — pay rules, fees, splits use jsonInit colours (blues / teals).
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
