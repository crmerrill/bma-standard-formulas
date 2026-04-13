import React from "react";
import FormSelect from "../../../components/FormSelect";
import type { ObjectiveDraftRow } from "./types";

interface Props {
  rows: ObjectiveDraftRow[];
  onChange: (rows: ObjectiveDraftRow[]) => void;
}

export default function ObjectiveBuilder({ rows, onChange }: Props) {
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
            <span className="text-muted-foreground">Type</span>
            <FormSelect
              value={row.objectiveType}
              onChange={(e) =>
                updateRow(rows, idx, {
                  objectiveType: e.target.value as ObjectiveDraftRow["objectiveType"],
                }, onChange)
              }
            >
              <option value="TARGET">TARGET</option>
              <option value="MINIMIZE">MINIMIZE</option>
              <option value="MAXIMIZE">MAXIMIZE</option>
            </FormSelect>
          </label>
          <NumberField
            label="Target"
            value={row.targetValue}
            onChange={(value) => updateRow(rows, idx, { targetValue: value }, onChange)}
            disabled={row.objectiveType !== "TARGET"}
          />
          <NumberField
            label="Weight"
            value={row.weight}
            onChange={(value) => updateRow(rows, idx, { weight: value ?? 1 }, onChange)}
          />
          <div className="flex items-end justify-end gap-1">
            <button
              type="button"
              onClick={() => removeRow(rows, idx, onChange)}
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
              id: `obj_${rows.length + 1}`,
              name: `objective_${rows.length + 1}`,
              metricPath: "",
              objectiveType: "TARGET",
              targetValue: 0,
              weight: 1,
              targetPrimitive: null,
              primitiveParams: {},
            },
          ])
        }
        className="px-2 py-1 rounded border border-border text-muted-foreground hover:text-foreground text-xs"
      >
        Add objective
      </button>
    </div>
  );
}

function updateRow(
  rows: ObjectiveDraftRow[],
  index: number,
  patch: Partial<ObjectiveDraftRow>,
  onChange: (rows: ObjectiveDraftRow[]) => void,
) {
  onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
}

function removeRow(
  rows: ObjectiveDraftRow[],
  index: number,
  onChange: (rows: ObjectiveDraftRow[]) => void,
) {
  onChange(rows.filter((_, i) => i !== index));
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
  disabled,
}: {
  label: string;
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}) {
  return (
    <label className="space-y-1">
      <span className="text-muted-foreground">{label}</span>
      <input
        type="number"
        value={value ?? ""}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full px-2 py-1 rounded border border-border bg-input-background text-foreground disabled:opacity-50"
      />
    </label>
  );
}
