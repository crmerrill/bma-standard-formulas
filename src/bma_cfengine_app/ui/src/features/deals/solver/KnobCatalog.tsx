import React from "react";
import type { KnobDraftRow } from "./types";

const KNOB_SUGGESTIONS = [
  "deal_knobs.class_a_coupon",
  "deal_knobs.class_b_coupon",
  "deal_knobs.oc_target_pct",
  "deal_knobs.reserve_target_pct",
];

interface Props {
  rows: KnobDraftRow[];
  onChange: (rows: KnobDraftRow[]) => void;
}

export default function KnobCatalog({ rows, onChange }: Props) {
  return (
    <div className="space-y-2">
      {rows.map((row, idx) => (
        <div key={row.id} className="grid grid-cols-1 md:grid-cols-6 gap-2 rounded border border-border p-2">
          <label className="space-y-1 md:col-span-2">
            <span className="text-muted-foreground">Knob path</span>
            <input
              list="knob-suggestions"
              value={row.knobPath}
              onChange={(e) => updateRow(rows, idx, { knobPath: e.target.value }, onChange)}
              className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
            />
          </label>
          <NumberField
            label="Lower"
            value={row.lower}
            onChange={(value) => updateRow(rows, idx, { lower: value ?? 0 }, onChange)}
          />
          <NumberField
            label="Upper"
            value={row.upper}
            onChange={(value) => updateRow(rows, idx, { upper: value ?? 0 }, onChange)}
          />
          <NumberField
            label="Initial"
            value={row.initial}
            onChange={(value) => updateRow(rows, idx, { initial: value ?? 0 }, onChange)}
          />
          <div className="flex items-end gap-1">
            <NumberField
              label="Step"
              value={row.stepHint}
              onChange={(value) => updateRow(rows, idx, { stepHint: value ?? 0.1 }, onChange)}
            />
            <button
              type="button"
              onClick={() => onChange(rows.filter((_, i) => i !== idx))}
              className="mb-0.5 px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground"
            >
              Remove
            </button>
          </div>
        </div>
      ))}
      <datalist id="knob-suggestions">
        {KNOB_SUGGESTIONS.map((option) => (
          <option key={option} value={option} />
        ))}
      </datalist>
      <button
        type="button"
        onClick={() =>
          onChange([
            ...rows,
            {
              id: `knob_${rows.length + 1}`,
              knobPath: KNOB_SUGGESTIONS[0],
              lower: 0,
              upper: 10,
              initial: 5,
              stepHint: 0.25,
            },
          ])
        }
        className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground text-xs"
      >
        Add knob
      </button>
    </div>
  );
}

function updateRow(
  rows: KnobDraftRow[],
  index: number,
  patch: Partial<KnobDraftRow>,
  onChange: (rows: KnobDraftRow[]) => void,
) {
  onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number;
  onChange: (value: number | null) => void;
}) {
  return (
    <label className="space-y-1 block">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
      />
    </label>
  );
}
