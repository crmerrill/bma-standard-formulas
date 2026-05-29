/**
 * Custom hook: Blockly lifecycle with ResizeObserver.
 *
 * Simplified — no dynamic reference blocks needed.
 * Targets carry their own properties; property panel syncs by name.
 */
import { useEffect, useRef, useState } from "react";

interface UseBlocklyWorkspaceOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  blocks: any[];
  toolbox: any;
  theme: any;
  renderer?: string;
  onChange?: (workspace: any) => void;
}

function updateBondFieldVisibility(block: any) {
  if (!block || block.type !== "bond_target") return;
  const isFloating = block.getFieldValue("BOND_TYPE") === "FLOATING";
  const indexLabel = block.getField("INDEX_LABEL");
  const indexField = block.getField("INDEX_NAME");
  const spreadLabel = block.getField("SPREAD_LABEL");
  const marginField = block.getField("MARGIN");

  if (!isFloating) {
    if (indexField && block.getFieldValue("INDEX_NAME")) {
      indexField.setValue("SOFR");
    }
    if (marginField && block.getFieldValue("MARGIN") !== "0") {
      marginField.setValue(0 as any);
    }
  }

  indexLabel?.setVisible?.(isFloating);
  indexField?.setVisible?.(isFloating);
  spreadLabel?.setVisible?.(isFloating);
  marginField?.setVisible?.(isFloating);
  block.render?.();
}

export function useBlocklyWorkspace({
  containerRef,
  blocks,
  toolbox,
  theme,
  renderer = "zelos",
  onChange,
}: UseBlocklyWorkspaceOptions) {
  const workspaceRef = useRef<any>(null);
  const blocklyRef = useRef<any>(null);
  const [ready, setReady] = useState(false);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  useEffect(() => {
    let disposed = false;
    let ro: ResizeObserver | null = null;
    let raf: number | null = null;

    async function init() {
      const container = containerRef.current;
      if (!container) return;

      const Blockly = await import("blockly");
      blocklyRef.current = Blockly;
      if (disposed) return;

      for (const block of blocks) {
        Blockly.Blocks[block.type] = {
          init(this: any) { this.jsonInit(block); },
        };
      }
      try {
        Blockly.Extensions.register("bond_target_dynamic_fields", function() {
          const block = this as any;
          const bondType = block.getField("BOND_TYPE");
          if (bondType?.setValidator) {
            bondType.setValidator((next: string) => {
              setTimeout(() => updateBondFieldVisibility(block), 0);
              return next;
            });
          }
          setTimeout(() => updateBondFieldVisibility(block), 0);
        });
      } catch {
        // extension already registered in a prior workspace mount
      }

      // Dynamic account dropdown: scans the workspace for declared accounts
      // and populates the ACCOUNT_TYPE dropdown. Runs on block init and
      // refreshes whenever the workspace changes via onWorkspaceChange.
      try {
        Blockly.Extensions.register("account_type_dynamic_fields", function() {
          const block = this as any;
          // Refresh the account dropdown options from the current workspace.
          function refreshAccountOptions() {
            const ws = block.workspace;
            if (!ws) return;
            const field = block.getField("ACCOUNT_TYPE");
            if (!field) return;
            const names: string[] = [];
            for (const b of ws.getAllBlocks(false)) {
              if (b.type === "account_target" && b.id !== block.id) {
                const n = b.getFieldValue("ACCOUNT_TYPE");
                if (n && !names.includes(n)) names.push(n);
              }
            }
            // Hardcoded standard account names always available.
            const standards = ["RESERVE", "PREFUNDING", "SPREAD_ACCOUNT", "REVOLVING", "PAYMENT"];
            for (const s of standards) {
              if (!names.includes(s)) names.push(s);
            }
            const current = field.getValue() || names[0];
            const opts: [string, string][] = names.map((n) => [n, n]);
            if (!names.includes(current)) opts.unshift([current, current]);
            try { field.menuGenerator_ = opts; } catch { /* read-only */ }
          }
          setTimeout(refreshAccountOptions, 50);
        });
      } catch {
        // extension already registered
      }

      let resolvedTheme = theme;
      if (typeof theme === "object" && theme.name) {
        resolvedTheme = Blockly.Theme.defineTheme(theme.name, theme);
      }

      const workspace = Blockly.inject(container, {
        toolbox,
        theme: resolvedTheme,
        renderer,
        grid: { spacing: 24, length: 2, colour: "#1e293b", snap: true },
        zoom: {
          controls: true, wheel: true,
          // +15%, then +10% more default zoom for readability.
          startScale: 0.633, maxScale: 2, minScale: 0.25, scaleSpeed: 1.1,
        },
        trashcan: true,
        move: { scrollbars: true, drag: true, wheel: true },
        sounds: false,
      });

      if (disposed) { workspace.dispose(); return; }
      workspaceRef.current = workspace;

      function doResize() {
        if (raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => {
          if (workspaceRef.current && blocklyRef.current) {
            blocklyRef.current.svgResize(workspaceRef.current);
          }
        });
      }

      ro = new ResizeObserver(doResize);
      ro.observe(container);
      doResize();
      workspace.scrollCenter();
      setTimeout(doResize, 100);
      setTimeout(() => workspace.scrollCenter(), 120);
      setTimeout(doResize, 300);
      setTimeout(() => workspace.scrollCenter(), 320);

      let timer: ReturnType<typeof setTimeout> | null = null;
      workspace.addChangeListener((event: any) => {
        if (event?.type === "change" && event?.element === "field") {
          const changed = event.blockId ? workspace.getBlockById(event.blockId) : null;
          if (changed?.type === "bond_target") {
            updateBondFieldVisibility(changed);
          }
          synchronizeBondTargets(workspace, event.blockId);
        }
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          if (onChangeRef.current && workspaceRef.current) {
            onChangeRef.current(workspaceRef.current);
          }
        }, 80);
      });

      setReady(true);
    }

    init();

    return () => {
      disposed = true;
      if (raf) cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
      if (workspaceRef.current) {
        workspaceRef.current.dispose();
        workspaceRef.current = null;
      }
      setReady(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef]);

  return { workspace: workspaceRef.current, ready };
}

function synchronizeBondTargets(workspace: any, changedBlockId: string | null | undefined) {
  if (!changedBlockId) return;
  const changed = workspace.getBlockById(changedBlockId);
  if (!changed || changed.type !== "bond_target") return;
  const name = changed.getFieldValue("NAME");
  if (!name) return;

  const canonical = {
    BOND_TYPE: changed.getFieldValue("BOND_TYPE"),
    PAY_MODE: changed.getFieldValue("PAY_MODE"),
    FACE_AMT: changed.getFieldValue("FACE_AMT"),
    SIZE_PCT_POOL: changed.getFieldValue("SIZE_PCT_POOL"),
    COUPON: changed.getFieldValue("COUPON"),
    INDEX_NAME: changed.getFieldValue("BOND_TYPE") === "FLOATING" ? changed.getFieldValue("INDEX_NAME") : "SOFR",
    MARGIN: changed.getFieldValue("BOND_TYPE") === "FLOATING" ? changed.getFieldValue("MARGIN") : 0,
    ACCRUAL: changed.getFieldValue("ACCRUAL"),
  };

  for (const block of workspace.getAllBlocks(false)) {
    if (block.type !== "bond_target" || block.id === changed.id) continue;
    if (block.getFieldValue("NAME") !== name) continue;
    for (const [field, value] of Object.entries(canonical)) {
      const fieldRef = block.getField(field);
      if (!fieldRef) continue;
      if (block.getFieldValue(field) !== value) {
        fieldRef.setValue(value as any);
      }
    }
    updateBondFieldVisibility(block);
  }
  updateBondFieldVisibility(changed);
}
