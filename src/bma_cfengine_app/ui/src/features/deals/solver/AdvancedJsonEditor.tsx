import React from "react";
import type { AdvancedJsonState } from "./types";

interface Props {
  state: AdvancedJsonState;
  onChange: (next: AdvancedJsonState) => void;
  onValidate: () => void;
  onSyncFromBuilder: () => void;
  onApplyToBuilder: () => void;
}

export default function AdvancedJsonEditor({
  state,
  onChange,
  onValidate,
  onSyncFromBuilder,
  onApplyToBuilder,
}: Props) {
  return (
    <div className="space-y-2">
      <textarea
        value={state.jsonText}
        onChange={(e) =>
          onChange({
            ...state,
            jsonText: e.target.value,
            parseError: null,
          })
        }
        rows={12}
        className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground text-xs"
      />
      {state.parseError && <div className="text-[11px] text-destructive">{state.parseError}</div>}
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onValidate}
          className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          Validate JSON
        </button>
        <button
          type="button"
          onClick={onSyncFromBuilder}
          className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          Sync from builder
        </button>
        <button
          type="button"
          onClick={onApplyToBuilder}
          className="px-2 py-1 rounded border border-border text-xs text-muted-foreground hover:text-foreground"
        >
          Apply JSON to builder
        </button>
        <span className="text-[11px] text-muted-foreground">
          {state.lastSyncedAt ? `Last sync: ${new Date(state.lastSyncedAt).toLocaleTimeString()}` : "Not synced"}
        </span>
      </div>
    </div>
  );
}
