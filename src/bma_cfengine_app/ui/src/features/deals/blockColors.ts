/**
 * Dynamic colors for target blocks only.
 *
 * Pay rules keep their static blues / blue-greens from block definitions (calm
 * “structure” layer). Targets inside them use saturated, well-separated hues so
 * tranches are scannable at a glance:
 *   — Bonds: red → orange (warm, high spread)
 *   — Accounts: emerald / jade greens (clearly not blue pay rules)
 *   — Residuals: violet → purple (equity / remainder read)
 *
 * Each family uses hash + index + large primes so similar names still diverge;
 * saturation/lightness vary in bands that stay readable on the dark workspace.
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
  l = Math.max(0, Math.min(100, l));

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

/** Bonds — reds through orange (≈0°–50°), wide spread via hash + index primes */
export function bondColor(name: string, index: number): string {
  const h = hashName(name) + index * 7919;
  const hue = (h + index * 47) % 51; // 0–50: crimson → orange
  const sat = 50 + ((h >>> 2) % 28); // 50–77
  const light = 38 + ((h >>> 6) % 20); // 38–57
  return hslToHex(hue, Math.min(sat, 80), Math.min(light, 58));
}

/**
 * Accounts — greens (≈108°–158°), away from pay-rule teals (~175°+) and bonds.
 */
export function accountColor(name: string, index: number): string {
  const h = hashName(name) + index * 5003;
  const hue = 108 + (h % 52) + (index * 7) % 12;
  const sat = 46 + ((h >>> 2) % 26);
  const light = 36 + ((h >>> 6) % 18);
  return hslToHex(Math.min(Math.max(hue, 108), 165), Math.min(sat, 76), Math.min(light, 56));
}

/** Residuals — violet / purple / magenta (≈258°–320°) */
export function residualColor(name: string, index: number): string {
  const h = hashName(name) + index * 3001;
  const hue = 258 + (h % 64) + (index * 9) % 14;
  const sat = 44 + ((h >>> 2) % 28);
  const light = 40 + ((h >>> 6) % 16);
  return hslToHex(Math.min(Math.max(hue, 258), 322), Math.min(sat, 74), Math.min(light, 56));
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
