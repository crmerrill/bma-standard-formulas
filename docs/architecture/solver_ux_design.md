# Solver UX Design Principles

This document is the contract for how new solver tools are built in this
project — both the Python orchestration layer and the Structuring Studio
UI. It exists because the first iteration of the solver UI was a generic
"build a SolverSpec" form that exposed raw IR field names (`knob_path`,
`primitive_params`, `targetPrimitive`, `WaterfallTargetPrimitive`) and
required users to assemble objectives, constraints, and knobs piece by
piece. That works for someone who already has the deal architecture
fully internalized, but it fails for the actual user (a structurer who
wants to balance the deal, hit a target WAL, or test a stress) who is
trying to express an *outcome*.

The principles below are derived from reviewing how Excel Goal Seek,
Bloomberg's BVAL/spread solvers, Tableau what-if parameters, the TI
BAII Plus / HP 12C TVM solver, Linear's keyboard shortcuts, and Apple,
Google Material, GitHub Primer, and Mailchimp content-style guidelines
handle structurally similar problems. The summary: **users pick the
*outcome* they want, the system builds the spec, the spec is editable
behind progressive disclosure**.

## Naming and language

### Outcomes, not mechanics

Solver templates are named after **what they do for the user**, in
verb-led sentence-case prose. Not after the math.

| Bad (what we have today)                 | Good (target)                                  |
| ----------------------------------------- | ---------------------------------------------- |
| Balanced Coupon + WAL                     | Balance the deal                               |
| Fast Feasible Search                      | Find a feasible deal quickly                   |
| Prime Jumbo: CumLoss + No Shortfall       | Pass the cumulative-loss test                  |
| auto_tieout_carry                         | Balance the deal                               |
| solver_template_family / target_primitive | (hidden — UI-internal)                         |

### Plain-language tooltips, every time

Every field with a domain-specific term has a one-sentence tooltip that
explains it without jargon. The tooltip *replaces* the field label for
beginners; experts can ignore it.

```
Implied residual yield  ⓘ
   "What return the residual class would need to balance the deal,
    given the bond coupons and pool yield. 8-15% is typical."
```

Domain terms that need plain-language tooltips: implied residual yield,
duration, convexity, WAL, OC test, IC test, PAC schedule, support
tranche, accrual class, cum-loss multiple, stepdown trigger, residual
class.

### Sentence case, conversational copy

Headings and labels are sentence case. Buttons are verb-led, present
tense. Status messages are conversational, not stack-trace-y.

| Bad                          | Good                                          |
| ---------------------------- | --------------------------------------------- |
| EXECUTE SOLVER               | Find the coupons                              |
| RUN OPTIMIZER                | Balance the deal                              |
| FAILED: ConvergenceError     | Couldn't converge in 24 tries — try widening the coupon range. |
| OBJECTIVE BUILDER            | What we're solving for                        |
| KNOB CATALOG + BOUNDS        | What I can adjust                             |

### No raw IR field names visible to users

The user should never see `knob_path`, `deal_knobs.X`, `primitive_params`,
`metric_path`, `targetPrimitive`, `objectiveType`. These are internal.

If the user picks "Class A coupon" from a list, the system maps that to
the IR path `deal_knobs.class_a_coupon` behind the scenes. The list
comes from the deal definition (bonds with their `name` field), not
from a free-form text input.

## Layout: progressive disclosure in three levels

Every solver tool has the same three-level layout. The user always lands
at level 1.

### Level 1 — The card

A single card on the DealEditor with:

- **Title** (verb-led): e.g., "Balance the deal"
- **One-line summary**: "Find coupons that fit the pool and leave a
  reasonable return for the residual."
- **One primary input** (the most important slider/number/select)
- **One primary action button**: "Find the coupons" (specific verb, not
  "Run")
- **Estimated runtime hint**: "≈30 seconds" — sets expectations.
- **Chevron / link**: "Customize" — opens level 2.

### Level 2 — Customize panel (collapsed by default)

Reveals:

- **What I'll change**: list of current deal items (e.g., bond coupons)
  with sliders/checkboxes. Pre-filled from the deal IR. Each row shows
  the current value and a default range; user can untick a row to lock
  it.
- **What stays the same**: explicit, non-editable list of locked things
  (tranche sizes, waterfall priority, fees, etc.). Builds trust by
  showing what the solver *won't* touch.
- **Constraints**: pre-filled from sensible defaults; user can edit
  inline or reset to defaults.
- **Convergence settings**: max iterations, tolerance — with `(default)`
  labels and one-click reset.

### Level 3 — Advanced JSON

Hidden behind an "Edit raw spec" link at the bottom of the customize
panel. Most users never see this.

## Smart defaults from deal context

Templates pre-fill from the live deal IR. The UI shows the source of
each default in muted text next to the value:

```
Class A coupon range:   [4.50%]   ── ❲5.00% from your deal❳   [6.50%]
                         ↑ pre-filled lower bound  ↑ help text  ↑ pre-filled upper
```

Specific behaviors:

- **Knob list** = bonds in the deal that have an editable coupon
  (excluding zero-coupon, IO, and residual classes).
- **Knob bounds** = current value ± a sensible delta (e.g., ±100 bps for
  coupons; ±5% for sizes).
- **Initial value** = current value from the deal.
- **Constraints** = sensible defaults (e.g., "no coupon below floor",
  "monotonic ladder by seniority", "residual ≥ 0") — each editable.
- **Targets** = current published / industry midpoint (e.g., "12%
  residual yield" for the tie-out template).

When the user changes a default, mark it visually as "modified" and
show a "reset to deal value" link.

## Result presentation

After running, show:

- **One-line status**: "Done — implied residual yield is 11.8%, within
  the 8-15% target band."
- **Before/after table**: `Class | Was | Now | Δ` for every changed
  knob. Use color (subtle green / red) for direction; never solely
  rely on color (accessibility).
- **Two clear actions**: "Apply changes" (writes back to deal IR) and
  "Discard changes" (default). **Don't auto-apply** — let the user
  audit before committing.
- **Convergence diagnostics** behind a chevron: iterations used, final
  residual error, knob trajectory. Most users don't need this; advanced
  users want it on demand.

## Schema: solver template registry

Each template is a Python dataclass with rich UX metadata:

```python
@dataclass
class SolverTemplate:
    template_id: str                 # internal id, e.g., "auto_tieout_carry"
    title: str                       # "Balance the deal"
    one_line_summary: str            # "Find coupons that fit the pool..."
    description_md: str              # rich plain-English explanation
    category: str                    # "tie_out" | "size_to_target" | "stress" | ...

    # The single primary input the user sees on the level-1 card.
    primary_input: PrimaryInput      # e.g., target residual yield slider

    # How to derive the runnable SolverSpec from the deal + user inputs.
    knobs_pattern: KnobPattern       # which deal_knobs are tunable + bounds rule
    objective_pattern: ObjectivePattern   # what to minimize / target
    constraints_patterns: list[ConstraintPattern]   # default constraints

    # UX metadata
    estimated_runtime_seconds: int   # for the "≈30 seconds" hint
    locked_aspects: list[str]        # plain-English list for "What stays the same"
    tooltips: dict[str, str]         # plain-language definitions for jargon
    suitable_for_families: list[ProductFamily]   # "AGENCY", "PRIME_JUMBO", ...
```

This metadata travels with the template definition. The endpoint
`GET /deals/{id}/solver/templates` returns all available templates with
deal-aware defaults baked in. The endpoint
`POST /deals/{id}/solver/templates/{template_id}/instantiate` takes the
user's level-1 + level-2 inputs and returns a fully-formed
`SolverSpec` ready to run via the existing `POST /deals/{id}/solve`.

The legacy "build a SolverSpec from scratch" form remains available as
a power-user fallback (Level 3 advanced JSON), but it is not the
primary entry point.

## Migration plan

1. Add the `SolverTemplate` schema and registry alongside the existing
   `solver_catalog`.
2. Author the **Auto-Tieout** template as the first proper template
   following these principles.
3. Build the new "Solve for…" card layout in the DealEditor that
   surfaces templates as level-1 cards.
4. Migrate the existing `PRESETS`, `PRIME_JUMBO_PRESETS`, etc., into
   `SolverTemplate` form one-by-one. Each migration is a chance to
   improve copy and defaults.
5. Move the existing forms-first `SolverStudioPanel` behind an "Edit
   raw spec" link as level-3 advanced.
6. Once the old panels are no longer the primary flow, retire them.

## Examples

### Auto-Tieout (the first template)

```
┌─────────────────────────────────────────────────────────────┐
│ Balance the deal                                            │
│                                                             │
│ Find coupons that fit the pool and leave a reasonable       │
│ return for the residual.                                    │
│                                                             │
│ Target residual return: ─────●─── 12% ⓘ                     │
│ "Where you want the back-solved residual yield to land.     │
│  10-15% is typical."                                        │
│                                                             │
│ [Find the coupons]   ≈30 seconds                            │
│                                                             │
│ ▸ Customize what changes                                    │
└─────────────────────────────────────────────────────────────┘
```

After running:

```
┌─────────────────────────────────────────────────────────────┐
│ Done — implied residual return is 11.8%                     │
│                                                             │
│ Class | Was      | Now      | Δ                             │
│  A    | 5.50%    | 5.42%    | -8 bps                        │
│  B    | 6.25%    | 6.10%    | -15 bps                       │
│  C    | 7.00%    | 6.95%    | -5 bps                        │
│                                                             │
│ [Apply changes]   [Discard]   ▸ Show convergence details    │
└─────────────────────────────────────────────────────────────┘
```

### Future templates (designed against the same shape)

- **Size the bonds**: pick target subordination, solver finds bond
  sizes that hit it.
- **Hit the WAL**: pick target WAL for the senior, solver tunes
  schedule or coupon to land it.
- **Stress for losses**: pick a cum-loss multiple, solver checks
  whether the deal still passes triggers.
- **Find the breakeven prepay speed**: at what PSA does the IO yield
  go negative?

Each follows the same level-1 card with one primary input, level-2
customize panel, and level-3 advanced.

## What this *does not* prescribe

- **Visual style**: handled by the design tokens in
  `src/bma_cfengine_app/ui/src/components/system/`. Templates render
  through the same `SurfaceCard`, `MetricCard`, `FormSelect`, etc.
- **Solver engine**: the underlying optimization algorithm
  (`scipy.optimize`, custom genetic, etc.) is an implementation detail
  of `solve_deal`. Templates are presentation layer over the same
  engine.
- **Authentication / authorization**: solver runs are gated by the
  same auth as deal runs.

## Acceptance criteria for new templates

A new solver template is "ready" when:

1. The level-1 card has a verb-led title, one-line summary, one
   primary input, one primary button, and a runtime hint.
2. Every domain term in the level-1 card has a tooltip with a
   plain-language definition.
3. The level-2 customize panel pre-fills from the live deal IR; every
   knob shows its current value with `from your deal` muted text.
4. The level-2 panel has a `What stays the same` section listing what
   the template will not change.
5. The result panel shows before/after, plain-English status, and
   explicit Apply/Discard actions.
6. Behind the chevron, the user can see the resolved `SolverSpec` (the
   level-3 advanced JSON view).
7. Acceptance is documented as a Python unit test that builds the
   template against a sample deal and verifies the resolved spec.

If a template does not meet these criteria, do not ship it.
