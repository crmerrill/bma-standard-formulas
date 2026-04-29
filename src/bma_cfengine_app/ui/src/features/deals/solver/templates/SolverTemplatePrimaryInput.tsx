import React from "react";
import { Info } from "lucide-react";
import type { PrimaryInput } from "../../../../services/api";
import { control, cx, text } from "../../../../components/system/ui";

interface Props {
  primary: PrimaryInput;
  value: number | string | boolean | null;
  onChange: (v: number | string | boolean) => void;
  disabled?: boolean;
}

/**
 * Renders the level-1 primary input widget for a solver template, per
 * `docs/architecture/solver_ux_design.md`. The widget shape is selected
 * by ``PrimaryInputKind``:
 *
 *   - NUMBER_SLIDER / PSA_SLIDER / PCT_SLIDER / BPS_SLIDER:
 *       a horizontal slider plus the live numeric value.
 *   - NUMBER_INPUT: a bare number field.
 *   - CHOICE: a small set of radio-style pills.
 *   - BOOLEAN: a toggle.
 *
 * The label is sentence case; the tooltip is shown via an info icon
 * next to the label and replaces jargon definitions per the design doc.
 */
export default function SolverTemplatePrimaryInput({
  primary,
  value,
  onChange,
  disabled,
}: Props) {
  const isSlider =
    primary.kind === "NUMBER_SLIDER" ||
    primary.kind === "PSA_SLIDER" ||
    primary.kind === "PCT_SLIDER" ||
    primary.kind === "BPS_SLIDER";

  return (
    <div className="space-y-1.5">
      <label
        className="flex items-center gap-1 text-xs text-foreground"
        htmlFor={`primary-${primary.field_id}`}
      >
        <span>{primary.label}</span>
        <span title={primary.tooltip} className="text-muted-foreground cursor-help">
          <Info className="w-3 h-3 inline" aria-hidden />
        </span>
      </label>

      {isSlider && (
        <NumberSlider
          fieldId={primary.field_id}
          value={asNumber(value, asNumber(primary.default ?? 0, 0))}
          min={primary.min_value ?? 0}
          max={primary.max_value ?? 100}
          step={primary.step ?? 1}
          unit={primary.unit ?? ""}
          disabled={disabled}
          onChange={onChange}
        />
      )}

      {primary.kind === "NUMBER_INPUT" && (
        <div className="flex items-center gap-1.5">
          <input
            id={`primary-${primary.field_id}`}
            type="number"
            className={cx(control.inputBase, "max-w-[140px]")}
            value={asNumber(value, asNumber(primary.default ?? 0, 0))}
            min={primary.min_value ?? undefined}
            max={primary.max_value ?? undefined}
            step={primary.step ?? undefined}
            disabled={disabled}
            onChange={(e) => onChange(Number(e.target.value))}
          />
          {primary.unit && (
            <span className={text.bodyMuted}>{primary.unit}</span>
          )}
        </div>
      )}

      {primary.kind === "CHOICE" && (
        <div className="flex flex-wrap gap-1.5" role="radiogroup">
          {primary.choices.map((c) => {
            const checked = String(value ?? primary.default ?? "") === c.value;
            return (
              <button
                key={c.value}
                role="radio"
                aria-checked={checked}
                disabled={disabled}
                onClick={() => onChange(c.value)}
                className={cx(
                  "rounded border px-2.5 py-1 text-xs transition-colors text-left",
                  checked
                    ? "border-primary/40 bg-primary/15 text-primary"
                    : "border-border text-muted-foreground hover:bg-white/5 hover:text-foreground",
                )}
                title={c.subtitle}
              >
                <div>{c.label}</div>
                {c.subtitle && (
                  <div className="text-[10px] text-muted-foreground mt-0.5">{c.subtitle}</div>
                )}
              </button>
            );
          })}
        </div>
      )}

      {primary.kind === "BOOLEAN" && (
        <label className="inline-flex items-center gap-1.5 text-xs text-foreground">
          <input
            type="checkbox"
            disabled={disabled}
            checked={value === true || (value == null && primary.default === true)}
            onChange={(e) => onChange(e.target.checked)}
          />
          <span>{primary.label}</span>
        </label>
      )}
    </div>
  );
}

interface SliderProps {
  fieldId: string;
  value: number;
  min: number;
  max: number;
  step: number;
  unit: string;
  disabled?: boolean;
  onChange: (v: number) => void;
}

function NumberSlider({
  fieldId,
  value,
  min,
  max,
  step,
  unit,
  disabled,
  onChange,
}: SliderProps) {
  return (
    <div className="flex items-center gap-2">
      <input
        id={`primary-${fieldId}`}
        type="range"
        className="flex-1 accent-primary"
        value={value}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <div className="min-w-[64px] text-right text-xs text-foreground tabular-nums">
        {value.toLocaleString(undefined, {
          maximumFractionDigits: step < 0.5 ? 2 : 1,
        })}
        {unit && <span className="ml-0.5 text-muted-foreground">{unit}</span>}
      </div>
    </div>
  );
}

function asNumber(v: unknown, fallback: number): number {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return fallback;
}
