/**
 * IrPreviewPanel — displays the generated Deal IR JSON with error state and save action.
 */
import React from "react";
import { Save, AlertTriangle, Code2 } from "lucide-react";
import { MONO } from "../../lib/format";

interface IrPreviewPanelProps {
  irJson: string;
  errors: string[];
  onSave: () => void;
}

export default function IrPreviewPanel({ irJson, errors, onSave }: IrPreviewPanelProps) {
  const lineCount = irJson ? irJson.split("\n").length : 0;

  return (
    <div className="flex-1 flex flex-col min-h-0 min-w-[300px]">
      {/* Header */}
      <div className="flex items-center gap-2 mb-2 px-1">
        <Code2 className="w-3.5 h-3.5 text-muted-foreground" />
        <span className="text-xs font-medium text-foreground">Deal IR</span>
        {lineCount > 0 && (
          <span className="text-[10px] text-muted-foreground" style={MONO}>
            {lineCount} lines
          </span>
        )}
        <button
          onClick={onSave}
          disabled={errors.length > 0 || !irJson}
          className="ml-auto flex items-center gap-1.5 px-3 py-1 rounded text-[11px]
            font-medium transition-colors bg-primary/10 text-primary hover:bg-primary/20
            disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <Save className="w-3 h-3" />
          Save
        </button>
      </div>

      {/* Errors */}
      {errors.length > 0 && (
        <div className="mb-2 px-3 py-2 rounded-md border border-destructive/40 bg-destructive/10">
          {errors.map((e, i) => (
            <div key={i} className="flex items-start gap-1.5 text-[11px] text-destructive">
              <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />
              <span>{e}</span>
            </div>
          ))}
        </div>
      )}

      {/* JSON preview */}
      <pre
        className="flex-1 min-h-0 overflow-auto rounded-md border border-border
          bg-[#0d1220] px-3 py-2 text-[11px] leading-relaxed text-secondary-foreground"
        style={MONO}
      >
        {irJson || (
          <span className="text-muted-foreground italic">
            {"// 1. Drag a Deal block\n// 2. Add Bonds in Bond Definitions\n// 3. Add Sources (accounts)\n// 4. Build the Waterfall with rules\n//    containing bond targets"}
          </span>
        )}
      </pre>
    </div>
  );
}
