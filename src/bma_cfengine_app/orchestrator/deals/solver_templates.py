"""Solver template registry: outcome-led, deal-aware, UX-first.

Templates wrap the low-level :class:`SolverSpec` with the metadata
specified in ``docs/architecture/solver_ux_design.md``: a verb-led
title, plain-language tooltips, smart defaults derived from the live
deal IR, and explicit lists of "what changes" / "what stays the same".

The two public entry points are:

  - :func:`list_templates_for_deal` -- returns the list of
    :class:`SolverTemplateView` (template + deal-aware defaults baked
    in) that drive the level-1 cards on the DealEditor.

  - :func:`instantiate_template` -- takes a
    :class:`TemplateInstantiationRequest` (the user's level-1 + level-2
    edits) and returns a fully-resolved :class:`SolverSpec` ready to
    run via the existing solver service.

Authoring a new template is the contract documented in
``solver_ux_design.md``; if a template does not satisfy the acceptance
criteria there, do not register it.
"""
from __future__ import annotations

from typing import Any

from bma_standard_formulas.deals.schemas.ir import DealDefinition
from bma_standard_formulas.deals.schemas.solver import (
    ConstraintComparison,
    ConstraintSpec,
    KnobBound,
    ObjectiveSpec,
    ObjectiveType,
    SolverLayerSpec,
    SolverSpec,
    WaterfallTargetPrimitive,
)
from bma_standard_formulas.deals.schemas.solver_template import (
    KnobPattern,
    KnobSelectorKind,
    ObjectivePattern,
    PrimaryInput,
    PrimaryInputKind,
    ProductFamily,
    ResolvedKnob,
    SolverTemplate,
    SolverTemplateView,
    TemplateCategory,
    TemplateInstantiationRequest,
    TemplateInstantiationResponse,
)


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------


def _auto_tieout_template() -> SolverTemplate:
    """The first outcome-led template: 'Balance the deal'.

    Adjusts cash-paying bond coupons so the back-solved residual yield
    lands in a target band (default 12%, typical band 5-35%). This is
    the canonical structuring tie-out workflow.
    """
    return SolverTemplate(
        template_id="auto_tieout_carry",
        title="Balance the deal",
        one_line_summary=(
            "Find coupons that fit the pool and leave a reasonable return "
            "for the residual."
        ),
        description_md=(
            "**What this does.** Walks the bond coupons up or down so the "
            "implied return on the residual class lands near a target you "
            "pick. The implied residual return is back-solved from the "
            "duration-weighted carry equation -- it tells you what the "
            "residual class would have to earn for the deal economics to "
            "balance, given pool yield, bond yields, and durations.\n\n"
            "**When to use it.** Right after you've finished sizing bonds "
            "and want to set their coupons. Or whenever you've changed "
            "the pool, the ladder, or a fee and want to re-tune coupons "
            "to keep the residual in a sensible range.\n\n"
            "**What it does NOT change.** Tranche sizes, the waterfall "
            "priority, scheduled balances, fees, triggers, or trigger "
            "thresholds. If you want to resize bonds, use 'Size the "
            "bonds' instead."
        ),
        category=TemplateCategory.BALANCE_DEAL,
        suitable_for_families=[ProductFamily.ANY],
        primary_input=PrimaryInput(
            kind=PrimaryInputKind.NUMBER_SLIDER,
            field_id="target_residual_yield_pct",
            label="Target residual return",
            tooltip=(
                "Where you want the back-solved residual yield to land. "
                "10-15% is typical for prime jumbo and Non-QM/QRM. Below "
                "5% means the structure is too tight (residual barely "
                "earns); above 30% means bond coupons are too low and "
                "the structure leaves too much for the issuer."
            ),
            unit="%",
            default=12.0,
            min_value=0.0,
            max_value=30.0,
            step=0.5,
        ),
        knobs_pattern=KnobPattern(
            selector=KnobSelectorKind.BOND_COUPON,
            bps_delta=100.0,
            description=(
                "I'll adjust each cash-paying bond's coupon by up to "
                "+/- 100 bps of its current value. Zero-coupon classes "
                "(POs), notional IO classes, and the residual stay "
                "fixed."
            ),
        ),
        objective_pattern=ObjectivePattern(
            name="implied_residual_yield_target",
            objective_type=ObjectiveType.TARGET,
            metric_path="carry_tieout.implied_residual_ytm_cbe_pct",
            target_value_expr="primary_input",
            weight=1.0,
        ),
        constraint_patterns=[],
        estimated_runtime_seconds=30,
        locked_aspects=[
            "Tranche sizes",
            "Waterfall priority",
            "Scheduled balances (PAC, TAC)",
            "Fees",
            "Triggers",
            "Pool collateral",
        ],
        tooltips={
            "target_residual_yield_pct": (
                "Where you want the back-solved residual yield to land. "
                "10-15% is typical."
            ),
            "implied_residual_yield": (
                "What return the residual class would need to balance "
                "the deal, given the bond coupons and pool yield."
            ),
        },
        primary_button_label="Find the coupons",
        success_message_template=(
            "Done -- implied residual return is {result_value:.2f}%, "
            "target was {primary_input:.2f}%."
        ),
        max_iterations=24,
        convergence_tolerance_bps=25.0,
    )


# Ordered list of templates exposed to the UI. Order = display order on
# the DealEditor "Solve for..." section.
_REGISTERED_TEMPLATES: list[SolverTemplate] = [
    _auto_tieout_template(),
]


def all_templates() -> list[SolverTemplate]:
    """Return the registered templates in display order."""
    return list(_REGISTERED_TEMPLATES)


def get_template(template_id: str) -> SolverTemplate:
    """Return the template with the given id; raises KeyError if missing."""
    for tpl in _REGISTERED_TEMPLATES:
        if tpl.template_id == template_id:
            return tpl
    raise KeyError(f"Unknown solver template: {template_id!r}")


# ---------------------------------------------------------------------------
# Knob resolution: derive ResolvedKnobs from a deal IR
# ---------------------------------------------------------------------------


def _is_cash_paying_bond(bond) -> bool:
    """A bond gets a coupon knob iff it has a non-zero fixed/floating coupon
    AND it is not a residual / notional IO class.
    """
    tt = getattr(bond.tranche_type, "value", None) if bond.tranche_type else None
    if tt in {"RESIDUAL", "PSEUDO"}:
        return False
    if getattr(bond, "tracks_bonds", None):
        # Notional IO classes track an underlying balance and don't have
        # an editable coupon for tie-out purposes (their coupon = the
        # underlying class's coupon by construction).
        if isinstance(bond.tracks_bonds, dict) and "balance" in bond.tracks_bonds:
            return False
    coupon_type = getattr(bond.coupon_type, "value", None) if bond.coupon_type else None
    if coupon_type == "ZERO":
        return False
    if not bond.coupon or bond.coupon <= 0.0:
        return False
    return True


def _resolve_bond_coupon_knobs(
    deal: DealDefinition, pattern: KnobPattern
) -> list[ResolvedKnob]:
    out: list[ResolvedKnob] = []
    for bond in deal.bonds:
        if pattern.exclude_tranche_ids and bond.name in pattern.exclude_tranche_ids:
            continue
        if (
            pattern.include_only_tranche_ids
            and bond.name not in pattern.include_only_tranche_ids
        ):
            continue
        if not _is_cash_paying_bond(bond):
            continue
        current = float(bond.coupon or 0.0)
        if pattern.bps_delta is not None:
            delta_pct = pattern.bps_delta / 100.0
            lower = max(0.0, current - delta_pct)
            upper = current + delta_pct
        else:
            lower = max(0.0, current * (1.0 - pattern.delta_pct))
            upper = current * (1.0 + pattern.delta_pct)
        out.append(
            ResolvedKnob(
                knob_id=f"coupon_{bond.name}",
                knob_path=f"bonds[{bond.name}].coupon",
                label=f"Class {bond.name} coupon",
                unit="%",
                current_value=current,
                lower=round(lower, 6),
                upper=round(upper, 6),
                step=0.05,
                initial=current,
                description=(
                    f"Current coupon is {current:.3f}%. "
                    f"I'll consider {lower:.3f}% to {upper:.3f}%."
                ),
            )
        )
    return out


def _resolve_bond_size_knobs(
    deal: DealDefinition, pattern: KnobPattern
) -> list[ResolvedKnob]:
    out: list[ResolvedKnob] = []
    delta = pattern.delta_pct
    for bond in deal.bonds:
        if pattern.exclude_tranche_ids and bond.name in pattern.exclude_tranche_ids:
            continue
        if (
            pattern.include_only_tranche_ids
            and bond.name not in pattern.include_only_tranche_ids
        ):
            continue
        size = float(bond.notional or 0.0)
        if size <= 0.0:
            continue
        out.append(
            ResolvedKnob(
                knob_id=f"size_{bond.name}",
                knob_path=f"bonds[{bond.name}].notional",
                label=f"Class {bond.name} size",
                unit="$",
                current_value=size,
                lower=round(size * (1.0 - delta), 2),
                upper=round(size * (1.0 + delta), 2),
                step=max(1000.0, size * 0.005),
                initial=size,
                description=(
                    f"Current size is ${size:,.0f}. I'll consider "
                    f"+/- {int(delta * 100)}% of current."
                ),
            )
        )
    return out


def _resolve_explicit_knobs(pattern: KnobPattern) -> list[ResolvedKnob]:
    return [
        ResolvedKnob(
            knob_id=knob.knob_path,
            knob_path=knob.knob_path,
            label=knob.knob_path,
            unit="",
            current_value=knob.initial if knob.initial is not None else knob.lower,
            lower=knob.lower,
            upper=knob.upper,
            step=knob.step_hint or 0.05,
            initial=knob.initial,
            description="",
        )
        for knob in pattern.explicit_knobs
    ]


def resolve_knobs(deal: DealDefinition, pattern: KnobPattern) -> list[ResolvedKnob]:
    """Turn a knob pattern into a list of ResolvedKnobs against the deal."""
    if pattern.selector == KnobSelectorKind.BOND_COUPON:
        return _resolve_bond_coupon_knobs(deal, pattern)
    if pattern.selector == KnobSelectorKind.BOND_SIZE:
        return _resolve_bond_size_knobs(deal, pattern)
    if pattern.selector == KnobSelectorKind.EXPLICIT_LIST:
        return _resolve_explicit_knobs(pattern)
    return []  # DEAL_KNOB / FEE_RATE not yet implemented; falls through.


# ---------------------------------------------------------------------------
# Constraint resolution
# ---------------------------------------------------------------------------


def resolve_constraints(deal: DealDefinition, template: SolverTemplate) -> list[ConstraintSpec]:
    """Materialize default ConstraintSpecs from the template's patterns."""
    out: list[ConstraintSpec] = []
    for pat in template.constraint_patterns:
        out.append(
            ConstraintSpec(
                name=pat.name,
                metric_path=pat.metric_path or "",
                comparison=pat.comparison,
                value=pat.value,
                lower=pat.lower,
                upper=pat.upper,
                target_primitive=pat.target_primitive,
                primitive_params=dict(pat.primitive_params),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def template_view_for_deal(
    deal: DealDefinition, template: SolverTemplate
) -> SolverTemplateView:
    """Combine a template with deal-aware defaults to render the level-2 panel."""
    return SolverTemplateView(
        template=template,
        resolved_knobs=resolve_knobs(deal, template.knobs_pattern),
        resolved_constraints=resolve_constraints(deal, template),
    )


def list_templates_for_deal(deal: DealDefinition) -> list[SolverTemplateView]:
    """Return all registered templates with deal-aware defaults applied.

    The DealEditor renders one level-1 card per entry in this list.
    """
    return [template_view_for_deal(deal, tpl) for tpl in all_templates()]


def instantiate_template(
    deal: DealDefinition,
    template: SolverTemplate,
    request: TemplateInstantiationRequest,
) -> TemplateInstantiationResponse:
    """Apply the user's level-1 + level-2 edits to produce a runnable SolverSpec.

    This is where the abstract template + concrete user choices become
    a real ``SolverSpec`` the existing solver service can execute.
    """
    # Resolve knobs from the deal, then apply user overrides and locks.
    base_knobs = resolve_knobs(deal, template.knobs_pattern)
    locked = set(request.locked_knob_ids)
    final_knobs: list[KnobBound] = []
    for rk in base_knobs:
        if rk.knob_id in locked:
            continue
        override = request.knob_overrides.get(rk.knob_id)
        if override is not None:
            rk = override
        final_knobs.append(
            KnobBound(
                knob_path=rk.knob_path,
                lower=rk.lower,
                upper=rk.upper,
                initial=rk.initial if rk.initial is not None else rk.current_value,
                step_hint=rk.step,
            )
        )
    if not final_knobs:
        raise ValueError(
            "Template has no tunable knobs after applying user locks; "
            "ensure at least one knob is unlocked."
        )

    # Resolve the objective: bind primary_input value into target_value.
    primary_value = request.primary_input_value
    if primary_value is None:
        primary_value = template.primary_input.default
    if isinstance(primary_value, (int, float)):
        target_value = float(primary_value)
    else:
        target_value = None

    objective = ObjectiveSpec(
        name=template.objective_pattern.name,
        metric_path=template.objective_pattern.metric_path or "",
        objective_type=template.objective_pattern.objective_type,
        target_value=target_value,
        weight=template.objective_pattern.weight,
        target_primitive=template.objective_pattern.target_primitive,
        primitive_params=dict(template.objective_pattern.primitive_params),
    )

    # Resolve constraints and apply user overrides by name.
    base_constraints = resolve_constraints(deal, template)
    final_constraints: list[ConstraintSpec] = []
    for cs in base_constraints:
        override = request.constraint_overrides.get(cs.name)
        final_constraints.append(override if override is not None else cs)

    layer = SolverLayerSpec(
        layer_name="base",
        objectives=[objective],
        constraints=final_constraints,
        knobs=final_knobs,
        max_iterations=request.max_iterations_override or template.max_iterations,
        convergence_tolerance=(
            (request.convergence_tolerance_bps_override or template.convergence_tolerance_bps)
            / 10000.0
        ),
        warm_start_from_prior=True,
    )
    spec = SolverSpec(
        solver_name=f"template_{template.template_id}",
        layers=[layer],
        global_max_iterations=template.max_iterations * 5,
        checkpoint_every_n=5,
    )

    knob_summary = ", ".join(
        f"{knob.knob_path} in [{knob.lower:.3f}, {knob.upper:.3f}]"
        for knob in final_knobs
    )
    if isinstance(primary_value, (int, float)):
        primary_str = f"{float(primary_value):.2f}{template.primary_input.unit or ''}"
    else:
        primary_str = str(primary_value)
    summary = (
        f"{template.title} -> "
        f"{template.primary_input.label}={primary_str}, "
        f"adjusting {len(final_knobs)} knob(s): {knob_summary}"
    )

    return TemplateInstantiationResponse(
        template_id=template.template_id,
        spec=spec,
        summary=summary,
    )
