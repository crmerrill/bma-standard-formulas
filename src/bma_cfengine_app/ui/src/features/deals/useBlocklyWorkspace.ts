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
          startScale: 0.85, maxScale: 2, minScale: 0.3, scaleSpeed: 1.1,
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
      setTimeout(doResize, 100);
      setTimeout(doResize, 300);

      let timer: ReturnType<typeof setTimeout> | null = null;
      workspace.addChangeListener(() => {
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
