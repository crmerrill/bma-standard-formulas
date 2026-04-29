import React, { useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Clock, Play } from "lucide-react";
import type {
  ResolvedKnob,
  SolverTemplateView,
} from "../../../../services/api";
import { control, cx, shell, text } from "../../../../components/system/ui";
import SolverTemplatePrimaryInput from "./SolverTemplatePrimaryInput";
import SolverTemplateCustomizePanel from "./SolverTemplateCustomizePanel";

interface Props {
  view: SolverTemplateView;
  busy: boolean;
  onRun: (params: {
    primaryInputValue: number | string | boolean | null;
    lockedKnobIds: string[];
    knobOverrides: Record<string, ResolvedKnob>;
  }) => Promise<void> | void;
  /** Optional last-status to render below the card after a run completes. */
  status?:
    | { kind: "idle" }
    | { kind: "running"; message: string }
    | { kind: "ok"; message: string }
    | { kind: "error"; message: string };
}

/**
 * Level-1 solver-template card per the contract in
 * `docs/architecture/solver_ux_design.md`:
 *
 *   - Verb-led title and one-line summary.
 *   - Single primary input (the most important slider/number/select).
 *   - One primary action button with a verb-led, template-specific
 *     label ("Find the coupons", not "Run").
 *   - Estimated runtime hint to set expectations ("≈30 seconds").
 *   - "Customize" chevron that reveals level-2 (the customize panel)
 *     collapsed by default.
 *
 * The card is purely presentational here -- the actual instantiate +
 * solve round-trip happens in the parent container, so this component
 * stays reusable and easy to test.
 */
export default function SolverTemplateCard({ view, busy, onRun, status }: Props) {
  const { template, resolved_knobs, resolved_constraints } = view;
  const [primaryValue, setPrimaryValue] = useState<
    number | string | boolean | null
  >(template.primary_input.default ?? null);
  const [lockedKnobIds, setLockedKnobIds] = useState<Set<string>>(
    () => new Set(resolved_knobs.filter((k) => k.locked).map((k) => k.knob_id)),
  );
  const [customizeOpen, setCustomizeOpen] = useState<boolean>(false);

  const tunableKnobCount = useMemo(
    () => resolved_knobs.filter((k) => !lockedKnobIds.has(k.knob_id)).length,
    [resolved_knobs, lockedKnobIds],
  );
  const allKnobsLocked =
    resolved_knobs.length > 0 && tunableKnobCount === 0;

  const toggleLocked = (knobId: string) => {
    setLockedKnobIds((prev) => {
      const next = new Set(prev);
      if (next.has(knobId)) next.delete(knobId);
      else next.add(knobId);
      return next;
    });
  };

  const handleRun = async () => {
    await onRun({
      primaryInputValue: primaryValue,
      lockedKnobIds: Array.from(lockedKnobIds),
      knobOverrides: {},
    });
  };

  return (
    <div className={cx(shell.card, "p-4 space-y-3")}>
      <header className="space-y-1">
        <h3 className="text-sm font-medium text-foreground">{template.title}</h3>
        <p className="text-xs text-muted-foreground">{template.one_line_summary}</p>
      </header>

      <SolverTemplatePrimaryInput
        primary={template.primary_input}
        value={primaryValue}
        onChange={setPrimaryValue}
        disabled={busy}
      />

      <div className="flex items-center gap-2 pt-1">
        <button
          type="button"
          className={cx(control.buttonPrimary, "inline-flex items-center gap-1.5")}
          onClick={handleRun}
          disabled={busy || allKnobsLocked}
          title={
            allKnobsLocked
              ? "All knobs are locked. Untick a knob in 'Customize' so the solver has something to adjust."
              : undefined
          }
        >
          <Play className="w-3 h-3" aria-hidden />
          {busy ? "Working…" : template.primary_button_label}
        </button>
        <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
          <Clock className="w-3 h-3" aria-hidden />
          ≈{template.estimated_runtime_seconds}s
        </span>

        <button
          type="button"
          className={cx(
            control.buttonGhost,
            "ml-auto inline-flex items-center gap-1",
          )}
          onClick={() => setCustomizeOpen((v) => !v)}
          aria-expanded={customizeOpen}
        >
          {customizeOpen ? (
            <ChevronDown className="w-3 h-3" aria-hidden />
          ) : (
            <ChevronRight className="w-3 h-3" aria-hidden />
          )}
          {customizeOpen ? "Hide customize" : "Customize"}
        </button>
      </div>

      {status && status.kind !== "idle" && (
        <div
          className={cx(
            "rounded-md border px-2.5 py-1.5 text-xs",
            status.kind === "running" && "border-border bg-grid-row-hover text-muted-foreground",
            status.kind === "ok" && "border-engine-green/30 bg-engine-green/10 text-engine-green",
            status.kind === "error" && "border-destructive/30 bg-destructive/10 text-destructive",
          )}
          role="status"
        >
          {status.message}
        </div>
      )}

      {customizeOpen && (
        <SolverTemplateCustomizePanel
          template={template}
          knobs={resolved_knobs}
          constraints={resolved_constraints}
          lockedKnobIds={lockedKnobIds}
          onToggleLocked={toggleLocked}
        />
      )}

      {allKnobsLocked && customizeOpen && (
        <div className={text.bodyMuted}>
          All knobs are locked. The solver needs at least one knob to adjust;
          untick a row above.
        </div>
      )}
    </div>
  );
}
