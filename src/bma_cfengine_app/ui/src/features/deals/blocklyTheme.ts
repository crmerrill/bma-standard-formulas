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

/* --- Block body labels (non-editable: "→", "face $", "cpn", etc.) ---
   These render on the block's colored background. Blockly computes their
   color automatically from block brightness. We set the font but leave the
   fill alone so Blockly's white/black auto-choice is preserved. */
.blocklyText {
  font-family: 'Inter', system-ui, sans-serif !important;
  font-size: 11px !important;
  font-weight: 500 !important;
}

/* --- Editable field backgrounds — white so text is always legible ---
   .blocklyFieldRect is the standard body rect for text/number/dropdown fields.
   We target it by class, not by positional combinators, to avoid catching
   unrelated rects (e.g. dropdown indicator rects that have separate styling). */
.blocklyFieldRect {
  fill: #ffffff !important;
  fill-opacity: 1 !important;
  stroke: rgba(0,0,0,0.15) !important;
  rx: 3 !important;
}

/* Text inside all editable field bodies — dark */
.blocklyEditableText .blocklyText {
  fill: #111827 !important;
  font-weight: 500 !important;
}

/* Dropdown field text value */
.blocklyDropdownText {
  fill: #111827 !important;
  font-family: 'Inter', system-ui, sans-serif !important;
  font-size: 11px !important;
}

/* Dropdown arrow — the polygon/path element that draws the chevron.
   In Blockly v10 Zelos renderer, .blocklyDropDownArrow is the group
   containing the arrow polygon. Dark fill makes it visible on white. */
.blocklyDropDownArrow {
  fill: #374151 !important;
}
.blocklyDropDownArrow polygon,
.blocklyDropDownArrow path {
  fill: #374151 !important;
}

/* Don't re-style .blocklyDropdownRect (Blockly v10 doesn't use that class
   for the indicator; leaving it alone prevents accidental white-on-white). */

/* --- HTML input when editing a field (click to type) ---
   Blockly injects this element with inline styles; these !important rules
   override both the Blockly inline styles AND the dark-theme body styles.
   Goal: identical appearance to the SVG display mode (white bg, dark text,
   same font, same size — no visual change when you click). */
.blocklyHtmlInput {
  background: #ffffff !important;
  color: #111827 !important;
  border: 1px solid rgba(0,0,0,0.25) !important;
  border-radius: 3px !important;
  /* Match the SVG font exactly so the text doesn't jump size/family */
  font-family: 'Inter', system-ui, sans-serif !important;
  font-size: 11px !important;
  font-weight: 500 !important;
  padding: 1px 4px !important;
  outline: 2px solid rgba(245,158,11,0.5) !important;
  outline-offset: 0 !important;
  box-shadow: none !important;
  min-width: 40px !important;
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
