/**
 * BlocklyCanvas — properly sized container for the Blockly workspace.
 *
 * Key sizing rules (per Google's resizable workspace docs):
 *   - Parent div has position: relative and a known height
 *   - Blockly injection div has position: absolute and fills the parent
 *   - No overflow: hidden on the injection div itself
 */
import React, { useRef, useEffect } from "react";
import { Layers } from "lucide-react";
import { DEAL_BLOCKS } from "./blockDefinitions";
import { BMA_THEME_DEF, injectBlocklyCSS, removeBlocklyCSS } from "./blocklyTheme";
import { TOOLBOX_CONFIG } from "./toolboxConfig";
import { useBlocklyWorkspace } from "./useBlocklyWorkspace";

interface BlocklyCanvasProps {
  onChange: (workspace: any) => void;
}

export default function BlocklyCanvas({ onChange }: BlocklyCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    injectBlocklyCSS();
    return () => removeBlocklyCSS();
  }, []);

  const { ready } = useBlocklyWorkspace({
    containerRef,
    blocks: DEAL_BLOCKS,
    toolbox: TOOLBOX_CONFIG,
    theme: BMA_THEME_DEF,
    onChange,
  });

  return (
    <div className="flex flex-1 min-w-0 flex-col min-h-0 h-full">
      <div className="flex items-center gap-2 mb-2 px-1">
        <Layers className="w-3.5 h-3.5 text-primary" />
        <span className="text-xs font-medium text-foreground">Deal Workspace</span>
        <span className="text-xs text-muted-foreground ml-auto">
          Sources → Rules → Bonds
        </span>
      </div>
      {/* Parent: flex-1 fills available height, position relative for absolute child */}
      <div
        className="flex-1 min-h-0 rounded-md border border-border"
        style={{ position: "relative" }}
      >
        {/* Blockly injection target: absolutely fills the parent */}
        <div
          ref={containerRef}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
          }}
        />
        {!ready && (
          <div
            className="flex items-center justify-center bg-background/80"
            style={{ position: "absolute", inset: 0, zIndex: 10 }}
          >
            <span className="text-xs text-muted-foreground animate-pulse">
              Loading editor...
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
