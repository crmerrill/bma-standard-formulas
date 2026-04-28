"""Outcome-led solver template registry: schema for the Solve-for-X cards.

Templates wrap the existing low-level `SolverSpec` schema with the UX
metadata required by ``docs/architecture/solver_ux_design.md``: a
verb-led title, a one-line summary, a single primary input, smart
defaults derived from the live deal IR, plain-language tooltips, and
explicit lists of "what changes" / "what stays the same".

The flow is:

  1. ``GET /deals/{id}/solver/templates`` -> list[SolverTemplateView],
     each with deal-aware defaults baked in.

  2. User edits the level-1 primary input + optional level-2 customize
     fields in the Studio.

  3. ``POST /deals/{id}/solver/templates/{template_id}/instantiate``
     with the user's edits -> a fully resolved SolverSpec.

  4. ``POST /deals/{id}/solve`` with the resolved spec -> normal solver
     run.

The legacy "build a SolverSpec from scratch" endpoint remains for
power users behind level-3 advanced JSON; templates are the primary
entry point.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

from .solver import (
    ConstraintComparison,
    ConstraintSpec,
    KnobBound,
    ObjectiveSpec,
    ObjectiveType,
    SolverLayerSpec,
    SolverSpec,
    WaterfallTargetPrimitive,
)


# ---------------------------------------------------------------------------
# Primary input types (what the user sees on the level-1 card)
# ---------------------------------------------------------------------------


class PrimaryInputKind(str, Enum):
    """The widget that renders for the template's single level-1 input.

    Each kind maps to a small set of attributes the UI knows how to
    render. Keep this list short and concrete -- if a template needs an
    input that doesn't fit, extend this enum rather than smuggling in
    free-form widgets.
    """

    NUMBER_SLIDER = "NUMBER_SLIDER"      # continuous slider (e.g. target yield)
    NUMBER_INPUT = "NUMBER_INPUT"        # bare number with min/max validation
    PSA_SLIDER = "PSA_SLIDER"            # 0-1000% PSA, log-spaced ticks
    PCT_SLIDER = "PCT_SLIDER"            # percent slider, 0-100
    BPS_SLIDER = "BPS_SLIDER"            # basis points, e.g., -200 to +200
    CHOICE = "CHOICE"                    # one-of-N pill picker
    BOOLEAN = "BOOLEAN"                  # toggle


class PrimaryInput(BaseModel):
    """Definition of the level-1 primary input widget.

    Examples:

      PrimaryInput(
          kind=PrimaryInputKind.NUMBER_SLIDER,
          field_id="target_residual_yield_pct",
          label="Target residual return",
          tooltip="Where you want the back-solved residual yield to land. "
                  "10-15% is typical for prime jumbo and Non-QM/QRM.",
          unit="%",
          default=12.0,
          min_value=0.0,
          max_value=30.0,
          step=0.5,
      )

      PrimaryInput(
          kind=PrimaryInputKind.PSA_SLIDER,
          field_id="target_psa_speed",
          label="Target prepayment speed",
          tooltip="The constant PSA speed at which to evaluate the deal.",
          unit="% PSA",
          default=100.0,
          min_value=0.0,
          max_value=500.0,
          step=10.0,
      )

      PrimaryInput(
          kind=PrimaryInputKind.CHOICE,
          field_id="metric_to_target",
          label="What to target",
          tooltip="Pick the bond economics you want to balance against.",
          choices=[
              {"value": "implied_residual_yield",
               "label": "Implied residual return",
               "subtitle": "Most common -- a back-solved residual yield."},
              {"value": "stack_weighted_yield",
               "label": "Stack-weighted yield",
               "subtitle": "Senior-to-junior weighted by duration."},
          ],
          default="implied_residual_yield",
      )
    """

    kind: PrimaryInputKind
    field_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    tooltip: str = Field(min_length=1, description="Plain-language explanation.")

    # Numeric fields (used for NUMBER_*, PSA_*, PCT_*, BPS_*).
    unit: str | None = None
    default: float | str | bool | None = None
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None

    # Choice fields (used for CHOICE).
    choices: list[dict[str, str]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Knob pattern: how to derive tunable knobs from the deal IR
# ---------------------------------------------------------------------------


class KnobSelectorKind(str, Enum):
    """How a knob pattern selects which deal_knobs/bond fields to tune."""

    BOND_COUPON = "BOND_COUPON"          # all cash-coupon bonds (excl IO/PO/residual)
    BOND_SIZE = "BOND_SIZE"              # tranche `size_dollars`
    DEAL_KNOB = "DEAL_KNOB"              # explicit `deal_knobs.<key>`
    FEE_RATE = "FEE_RATE"                # fees[].rate_pct
    EXPLICIT_LIST = "EXPLICIT_LIST"      # caller supplies a fixed list


class KnobPattern(BaseModel):
    """Rule for deriving a list of `KnobBound`s from a deal IR.

    Fully resolved at template-instantiation time by reading the deal:

    - ``BOND_COUPON``: emits one knob per cash-coupon bond (excluding
      IO/PO/residual). Bounds default to ``current_coupon ± delta_pct``.
    - ``BOND_SIZE``: emits one knob per non-residual bond. Bounds
      default to ``current_size * (1 ± delta_pct)``.
    - ``DEAL_KNOB``: emits a knob with path ``deal_knobs.<key>``. Bounds
      pulled from the explicit ``bounds`` field.
    - ``FEE_RATE``: emits one knob per fee whose rate is non-null.
    - ``EXPLICIT_LIST``: pass-through; caller-supplied list of
      `KnobBound`s.

    The ``exclude_tranche_ids`` and ``include_only_tranche_ids`` filters
    let templates lock specific bonds (e.g., always lock the residual).
    """

    selector: KnobSelectorKind
    delta_pct: float = 0.20
    """For coupon/size knobs, the +/- range as a fraction of current value
    (0.20 = +/- 20%). Coupons typically use 0.20 (-20% / +20% of current);
    sizes typically use 0.10 (-10% / +10%)."""

    bps_delta: float | None = None
    """Optional absolute basis-point delta for coupon knobs. When set,
    bounds = ``current_pct +/- bps_delta/100``. Overrides ``delta_pct``
    for cleaner UI display when the user is thinking in bps."""

    exclude_tranche_ids: list[str] = Field(default_factory=list)
    include_only_tranche_ids: list[str] = Field(default_factory=list)

    explicit_knobs: list[KnobBound] = Field(default_factory=list)
    """Pre-built knob list for ``EXPLICIT_LIST`` selector. Empty
    otherwise."""

    description: str = ""
    """Plain-language description of what this knob pattern adjusts.
    Example: "Adjust each cash-paying bond's coupon by up to +/- 100 bps
    of its current value." Used in the Customize panel header."""


# ---------------------------------------------------------------------------
# Objective and constraint patterns
# ---------------------------------------------------------------------------


class ObjectivePattern(BaseModel):
    """How to build the level-1 objective from the user's primary input."""

    name: str = Field(min_length=1)
    objective_type: ObjectiveType = ObjectiveType.TARGET

    # The metric the solver is targeting. Either a metric_path (for
    # post-run metrics like "tranche_risk_summary[A].yield_pct") or a
    # waterfall target primitive (for engine-internal targets).
    metric_path: str | None = None
    target_primitive: WaterfallTargetPrimitive | None = None
    primitive_params: dict[str, Any] = Field(default_factory=dict)

    # The user's level-1 primary input is mapped into the target value
    # via this expression. The expression can reference the user's
    # input field_id (from PrimaryInput.field_id) and "deal" (the
    # canonical DealDefinition) and "context" (a small dict of derived
    # values like the pool yield).
    target_value_expr: str = "primary_input"

    weight: float = 1.0


class ConstraintPattern(BaseModel):
    """A constraint pattern that resolves to a `ConstraintSpec`."""

    name: str = Field(min_length=1)
    description: str = ""
    """Plain-language description for the Customize panel."""

    metric_path: str | None = None
    target_primitive: WaterfallTargetPrimitive | None = None
    primitive_params: dict[str, Any] = Field(default_factory=dict)

    comparison: ConstraintComparison
    value: float | None = None
    lower: float | None = None
    upper: float | None = None

    user_editable: bool = True
    """When False, the constraint is locked (shown in the "What stays the
    same" list) and the user cannot edit it from the customize panel."""


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


class TemplateCategory(str, Enum):
    """High-level grouping of templates for the UI.

    The Studio renders one section per category, so each user-facing
    name should describe the *outcome space* (verb-led).
    """

    BALANCE_DEAL = "BALANCE_DEAL"          # "Balance the deal" — tie-out
    SIZE_BONDS = "SIZE_BONDS"              # "Size the bonds" — to a CE / WAL target
    HIT_TARGET = "HIT_TARGET"              # "Hit a specific WAL or yield"
    STRESS_TEST = "STRESS_TEST"            # "Stress for losses" — what passes
    BREAK_EVEN = "BREAK_EVEN"              # "Find a break-even" — IO breakeven, etc.
    DIAGNOSTIC = "DIAGNOSTIC"              # "Why doesn't this fit?" — explainers


class ProductFamily(str, Enum):
    AGENCY = "AGENCY"
    PRIME_JUMBO = "PRIME_JUMBO"
    NON_QM_QRM = "NON_QM_QRM"
    CRT = "CRT"
    ANY = "ANY"


class SolverTemplate(BaseModel):
    """An outcome-led solver template per the solver UX design doc.

    See ``docs/architecture/solver_ux_design.md`` for the language and
    layout principles every template must satisfy.
    """

    template_id: str = Field(min_length=1, description="Internal id, snake_case.")
    title: str = Field(
        min_length=1,
        description="Verb-led card heading, sentence case. "
                    "Example: 'Balance the deal'.",
    )
    one_line_summary: str = Field(
        min_length=1,
        description="One sentence beneath the title. Plain English, no jargon. "
                    "Example: 'Find coupons that fit the pool and leave a "
                    "reasonable return for the residual.'",
    )
    description_md: str = Field(
        default="",
        description="Markdown body shown when the user expands 'Learn more'.",
    )
    category: TemplateCategory
    suitable_for_families: list[ProductFamily] = Field(
        default_factory=lambda: [ProductFamily.ANY],
        description="Which product families this template fits.",
    )

    # Level-1: the single primary input the user sees on the card.
    primary_input: PrimaryInput

    # How to assemble the runnable SolverSpec from the deal + user inputs.
    knobs_pattern: KnobPattern
    objective_pattern: ObjectivePattern
    constraint_patterns: list[ConstraintPattern] = Field(default_factory=list)

    # UX metadata.
    estimated_runtime_seconds: int = Field(
        default=30,
        description="For the '~Xs' hint on the action button.",
    )
    locked_aspects: list[str] = Field(
        default_factory=list,
        description="Plain-English list of what stays the same. "
                    "Example: ['Tranche sizes', 'Waterfall priority', 'Fees'].",
    )
    tooltips: dict[str, str] = Field(
        default_factory=dict,
        description="field_id -> plain-language definition. "
                    "Used for inline tooltips on any jargon term.",
    )
    primary_button_label: str = Field(
        default="Run",
        description="Verb-led action button label. Example: 'Find the coupons'.",
    )
    success_message_template: str = Field(
        default="Done.",
        description="Format string for the post-run status. Can reference "
                    "{primary_input}, {result_value}, etc.",
    )

    # Solver execution defaults baked in.
    max_iterations: int = 24
    convergence_tolerance_bps: float = 25.0


# ---------------------------------------------------------------------------
# View payload (what the API returns to the UI)
# ---------------------------------------------------------------------------


class ResolvedKnob(BaseModel):
    """A knob with deal-derived defaults baked in for the Customize panel.

    Each ResolvedKnob renders as one row in the level-2 'What I'll
    change' list. ``current_value`` is shown as the muted ``from your
    deal`` annotation; ``lower``/``upper`` populate the slider bounds;
    ``user_editable`` controls whether the slider is interactive.
    """

    knob_id: str
    """Internal id (e.g., 'coupon_class_a'). Maps to ``knob_path`` for
    the resolved SolverSpec."""

    knob_path: str
    """The IR path (e.g., 'bonds[A].coupon'). Hidden from the user."""

    label: str
    """User-facing label, sentence case. Example: 'Class A coupon'."""

    unit: str = "%"
    current_value: float
    lower: float
    upper: float
    step: float = 0.05
    initial: float | None = None

    locked: bool = False
    """When True, the row shows in a separate 'Locked' list."""

    description: str = ""


class SolverTemplateView(BaseModel):
    """Template + deal-aware defaults, returned by the GET endpoint."""

    template: SolverTemplate
    resolved_knobs: list[ResolvedKnob]
    resolved_constraints: list[ConstraintSpec]
    """Constraints with default values filled in from the deal context."""


# ---------------------------------------------------------------------------
# Instantiation request (what the user POSTs to apply level-1 + level-2 edits)
# ---------------------------------------------------------------------------


class TemplateInstantiationRequest(BaseModel):
    """User's level-1 + level-2 edits, sent to the instantiate endpoint."""

    primary_input_value: float | str | bool | None = None
    """The value of the level-1 PrimaryInput field. Type matches the
    template's ``PrimaryInput.kind``."""

    knob_overrides: dict[str, ResolvedKnob] = Field(default_factory=dict)
    """Per-knob overrides keyed by ``knob_id``. Knobs not present here
    use the deal-derived defaults."""

    constraint_overrides: dict[str, ConstraintSpec] = Field(default_factory=dict)
    """Per-constraint overrides keyed by constraint name."""

    locked_knob_ids: list[str] = Field(default_factory=list)
    """``knob_id``s the user explicitly locked from the Customize panel.
    These are removed from the resolved SolverSpec's knob list."""

    max_iterations_override: int | None = None
    convergence_tolerance_bps_override: float | None = None


class TemplateInstantiationResponse(BaseModel):
    """The fully resolved SolverSpec ready to run via /solve."""

    template_id: str
    spec: SolverSpec
    summary: str
    """One-line summary of what was instantiated, for the run history.
    Example: 'Balance the deal -> target residual return = 12.0%, "
    "adjusting coupons of A, B, C within +/-100 bps of current.'"""
