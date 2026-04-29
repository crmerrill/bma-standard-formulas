import React from "react";
import { Lock, ShieldCheck } from "lucide-react";
import type {
  ResolvedConstraint,
  ResolvedKnob,
  SolverTemplateMeta,
} from "../../../../services/api";
import { text } from "../../../../components/system/ui";

interface Props {
  template: SolverTemplateMeta;
  knobs: ResolvedKnob[];
  constraints: ResolvedConstraint[];
  lockedKnobIds: Set<string>;
  onToggleLocked: (knobId: string) => void;
}

/**
 * Level-2 customize panel per `docs/architecture/solver_ux_design.md`.
 *
 * Three sections, each with explicit copy:
 *
 *   - "What I'll change" — the resolved knob list. Each row shows the
 *     current deal value (`current_value`) and the default solver
 *     bounds. The user can lock individual knobs; the solver will not
 *     touch any locked knob. We keep the bounds read-only in this
 *     iteration; bounds-editing is a level-3 advanced feature.
 *
 *   - "What stays the same" — explicit, non-editable list from the
 *     template's ``locked_aspects`` field. Builds trust by showing
 *     what the solver will *not* touch (sizes, waterfall priority,
 *     fees, etc.). This list is templated, not deal-derived.
 *
 *   - "Constraints" — a read-only summary of the resolved constraints
 *     (e.g., 'no coupon below the floor', 'monotonic ladder'). For
 *     iteration 1, these are display-only; constraint editing is
 *     deferred to a follow-up.
 */
export default function SolverTemplateCustomizePanel({
  template,
  knobs,
  constraints,
  lockedKnobIds,
  onToggleLocked,
}: Props) {
  return (
    <div className="space-y-4 pt-3">
      <section>
        <h4 className={text.sectionTitle}>What I&apos;ll change</h4>
        <p className="text-[11px] text-muted-foreground mt-0.5 mb-2">
          The solver tunes these within the listed range. Untick a row to lock
          it.
        </p>
        {knobs.length === 0 ? (
          <div className="text-xs text-muted-foreground italic">
            This template has no tunable knobs for the current deal.
          </div>
        ) : (
          <div className="rounded border border-border divide-y divide-border">
            {knobs.map((k) => {
              const isLocked = lockedKnobIds.has(k.knob_id);
              return (
                <div
                  key={k.knob_id}
                  className="flex items-center gap-3 px-2.5 py-1.5 text-xs"
                >
                  <input
                    type="checkbox"
                    aria-label={`Allow solver to adjust ${k.label}`}
                    checked={!isLocked}
                    onChange={() => onToggleLocked(k.knob_id)}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={isLocked ? "text-muted-foreground line-through" : "text-foreground"}>
                        {k.label}
                      </span>
                      {isLocked && (
                        <Lock className="w-3 h-3 text-muted-foreground" aria-hidden />
                      )}
                    </div>
                    <div className="text-[11px] text-muted-foreground tabular-nums">
                      {fmt(k.current_value, k.unit)}{" "}
                      <span className="opacity-60">from your deal</span>
                    </div>
                  </div>
                  <div className="text-[11px] text-muted-foreground tabular-nums whitespace-nowrap">
                    {fmt(k.lower, k.unit)} – {fmt(k.upper, k.unit)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {template.locked_aspects.length > 0 && (
        <section>
          <h4 className={`${text.sectionTitle} flex items-center gap-1.5`}>
            <ShieldCheck className="w-3.5 h-3.5 text-engine-green" aria-hidden />
            What stays the same
          </h4>
          <p className="text-[11px] text-muted-foreground mt-0.5 mb-2">
            The solver won&apos;t touch any of these.
          </p>
          <ul className="space-y-1 text-xs text-muted-foreground">
            {template.locked_aspects.map((aspect, idx) => (
              <li key={`locked-${idx}`} className="flex items-start gap-1.5">
                <span aria-hidden className="text-engine-green">•</span>
                <span>{aspect}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {constraints.length > 0 && (
        <section>
          <h4 className={text.sectionTitle}>Constraints</h4>
          <p className="text-[11px] text-muted-foreground mt-0.5 mb-2">
            Pre-filled from the template. Editing constraints is in the
            advanced view.
          </p>
          <ul className="rounded border border-border divide-y divide-border">
            {constraints.map((c, idx) => (
              <li
                key={`constraint-${idx}-${c.name}`}
                className="px-2.5 py-1.5 text-xs"
              >
                <div className="text-foreground">{describeConstraint(c)}</div>
                {c.description && (
                  <div className="text-[11px] text-muted-foreground mt-0.5">
                    {c.description}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

function describeConstraint(c: ResolvedConstraint): string {
  const target = c.metric_path ?? c.target_primitive ?? c.name;
  switch (c.comparison) {
    case "GE":
      return `${target} ≥ ${c.value ?? "—"}`;
    case "LE":
      return `${target} ≤ ${c.value ?? "—"}`;
    case "EQ":
      return `${target} = ${c.value ?? "—"}`;
    case "BETWEEN":
      return `${c.lower ?? "—"} ≤ ${target} ≤ ${c.upper ?? "—"}`;
    default:
      return `${target} ${c.comparison} ${c.value ?? ""}`;
  }
}

function fmt(v: number, unit: string): string {
  const formatted = v.toLocaleString(undefined, { maximumFractionDigits: 3 });
  return unit ? `${formatted}${unit}` : formatted;
}
