import React from "react";
import FormSelect from "../../../components/FormSelect";
import type { ConstraintDraftRow } from "./types";

interface Props {
  rows: ConstraintDraftRow[];
  onChange: (rows: ConstraintDraftRow[]) => void;
}

export default function ConstraintBuilder({ rows, onChange }: Props) {
  return (
    <div className="space-y-2">
      {rows.map((row, idx) => (
        <div key={row.id} className="grid grid-cols-1 md:grid-cols-6 gap-2 rounded border border-border p-2">
          <Field
            label="Name"
            value={row.name}
            onChange={(value) => updateRow(rows, idx, { name: value }, onChange)}
          />
          <Field
            label="Metric path"
            value={row.metricPath}
            onChange={(value) => updateRow(rows, idx, { metricPath: value }, onChange)}
          />
          <label className="space-y-1">
            <span className="text-muted-foreground">Operator</span>
            <FormSelect
              value={row.operator}
              onChange={(e) =>
                updateRow(
                  rows,
                  idx,
                  { operator: e.target.value as ConstraintDraftRow["operator"] },
                  onChange,
                )
              }
            >
              <option value="GE">GE</option>
              <option value="LE">LE</option>
              <option value="EQ">EQ</option>
              <option value="BETWEEN">BETWEEN</option>
            </FormSelect>
          </label>
          <NumberField
            label={row.operator === "BETWEEN" ? "Min" : row.operator === "GE" ? "Value" : "Optional"}
            value={row.minValue}
            onChange={(value) => updateRow(rows, idx, { minValue: value }, onChange)}
          />
          <NumberField
            label={row.operator === "BETWEEN" ? "Max" : row.operator === "GE" ? "Optional" : "Value"}
            value={row.maxValue}
            onChange={(value) => updateRow(rows, idx, { maxValue: value }, onChange)}
          />
          <div className="flex items-end justify-end">
            <button
              type="button"
              onClick={() => onChange(rows.filter((_, i) => i !== idx))}
              className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground"
            >
              Remove
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={() =>
          onChange([
            ...rows,
            {
              id: `constraint_${rows.length + 1}`,
              name: `constraint_${rows.length + 1}`,
              metricPath: "",
              operator: "LE",
              minValue: null,
              maxValue: null,
              targetPrimitive: null,
              primitiveParams: {},
            },
          ])
        }
        className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground text-xs"
      >
        Add constraint
      </button>
    </div>
  );
}

function updateRow(
  rows: ConstraintDraftRow[],
  index: number,
  patch: Partial<ConstraintDraftRow>,
  onChange: (rows: ConstraintDraftRow[]) => void,
) {
  onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
}

function Field({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="text-muted-foreground">{label}</span>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
      />
    </label>
  );
}

function NumberField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
}) {
  return (
    <label className="space-y-1">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground"
      />
    </label>
  );
}
