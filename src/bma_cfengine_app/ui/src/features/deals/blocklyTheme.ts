/**
 * Blockly theme for BMA Engine dark UI.
 *
 * Uses Blockly's built-in dark theme as base, then applies muted block colors
 * and dark field backgrounds to match the app's navy/slate palette.
 */

export const BMA_THEME_DEF = {
  name: "bma_dark",
  base: "classic" as const,
  blockStyles: {
    // All blocks use the app's slate/navy palette with subtle differentiation
    // Primary = block face, Secondary = top highlight, Tertiary = shadow
    deal_blocks:    { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    bond_blocks:    { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    account_blocks: { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    fee_blocks:     { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    rule_blocks:    { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    trigger_blocks: { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    logic_blocks:   { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
    list_blocks:    { colourPrimary: "#1e293b", colourSecondary: "#334155", colourTertiary: "#0f172a" },
  },
  componentStyles: {
    workspaceBackgroundColour: "#0a0e17",
    toolboxBackgroundColour: "#0f172a",
    toolboxForegroundColour: "#cbd5e1",
    flyoutBackgroundColour: "#111827",
    flyoutForegroundColour: "#e1e4ea",
    flyoutOpacity: 0.97,
    scrollbarColour: "#334155",
    scrollbarOpacity: 0.6,
    insertionMarkerColour: "#f59e0b",
    insertionMarkerOpacity: 0.4,
    cursorColour: "#f59e0b",
  },
  fontStyle: {
    family: "'Inter', system-ui, sans-serif",
    weight: "500",
    size: 11,
  },
  startHats: false,
};

/**
 * CSS overrides — only for things the Blockly theme API cannot control.
 */
export const BLOCKLY_CSS_OVERRIDES = `
/* --- Toolbox tree rows --- */
.blocklyTreeRow {
  height: 30px !important;
  padding: 0 12px !important;
  margin: 1px 4px !important;
  border-radius: 4px !important;
  line-height: 30px !important;
}
.blocklyTreeRow:hover {
  background: rgba(255, 255, 255, 0.05) !important;
}
.blocklyTreeSelected {
  background: rgba(245, 158, 11, 0.12) !important;
}
.blocklyTreeLabel {
  font-size: 11px !important;
  font-family: 'Inter', system-ui, sans-serif !important;
  font-weight: 500 !important;
  color: #cbd5e1 !important;
}
.blocklyTreeSelected .blocklyTreeLabel {
  color: #f59e0b !important;
}
.blocklyTreeIcon {
  display: none !important;
}
.blocklyToolboxDiv {
  border-right: 1px solid #1e293b !important;
}

/* --- Block text --- */
.blocklyText {
  font-family: 'Inter', system-ui, sans-serif !important;
  fill: #e2e8f0 !important;
}
.blocklyDropdownText {
  font-family: 'Inter', system-ui, sans-serif !important;
  fill: #e2e8f0 !important;
}

/* --- Editable field rects: dark background instead of white --- */
.blocklyEditableText > .blocklyFieldRect,
.blocklyEditableText > rect {
  fill: rgba(0, 0, 0, 0.35) !important;
  stroke: rgba(255, 255, 255, 0.08) !important;
  rx: 4 !important;
}
/* Number and text field values should be light */
.blocklyEditableText .blocklyText {
  fill: #f1f5f9 !important;
}

/* --- Dropdown arrow --- */
.blocklyDropdownRect {
  fill: rgba(0, 0, 0, 0.3) !important;
  stroke: rgba(255, 255, 255, 0.06) !important;
  rx: 4 !important;
}

/* --- HTML input fields (inline editing) --- */
.blocklyHtmlInput {
  background: #1e293b !important;
  color: #f1f5f9 !important;
  border: 1px solid #475569 !important;
  border-radius: 4px !important;
  font-family: 'JetBrains Mono', monospace !important;
  font-size: 11px !important;
  padding: 2px 6px !important;
}

/* --- Dropdown menus (outside SVG) --- */
.blocklyDropDownDiv {
  background: #1e293b !important;
  border: 1px solid #334155 !important;
  border-radius: 6px !important;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.6) !important;
}
.blocklyMenuItem {
  color: #e2e8f0 !important;
  font-family: 'Inter', system-ui, sans-serif !important;
  font-size: 11px !important;
  padding: 6px 12px !important;
}
.blocklyMenuItemHighlight {
  background: rgba(245, 158, 11, 0.12) !important;
}

/* --- Flyout --- */
.blocklyFlyoutBackground {
  stroke: none !important;
  stroke-width: 0 !important;
}
.blocklyFlyoutScrollbar {
  opacity: 0.3 !important;
}

/* --- Workspace scrollbar --- */
.blocklyScrollbarBackground {
  fill: transparent !important;
  opacity: 0 !important;
}
.blocklyScrollbarHandle {
  rx: 3 !important;
}
.blocklySvg {
  background: #0a0e17 !important;
}

/* --- Connection highlights --- */
.blocklyHighlightedConnectionPath {
  stroke: #f59e0b !important;
  stroke-width: 3px !important;
}

/* --- Trashcan and zoom --- */
.blocklyTrash { opacity: 0.35 !important; }
.blocklyZoom > image { opacity: 0.4 !important; }
.blocklyZoom > image:hover { opacity: 0.7 !important; }

/* --- Input value sockets (the puzzle holes) --- */
.blocklyPathDark {
  fill: none !important;
}
`;

let _styleInjected = false;
let _styleElement: HTMLStyleElement | null = null;

export function injectBlocklyCSS(): void {
  if (_styleInjected) return;
  _styleElement = document.createElement("style");
  _styleElement.setAttribute("data-blockly-bma", "true");
  _styleElement.textContent = BLOCKLY_CSS_OVERRIDES;
  document.head.appendChild(_styleElement);
  _styleInjected = true;
}

export function removeBlocklyCSS(): void {
  if (_styleElement) {
    document.head.removeChild(_styleElement);
    _styleElement = null;
    _styleInjected = false;
  }
}
