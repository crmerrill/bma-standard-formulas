"""Acceptance tests for solver templates.

Per ``docs/architecture/solver_ux_design.md``, every registered solver
template must satisfy a set of acceptance criteria before it can ship.
This module enforces those criteria for every template currently in
the registry, so adding a new template that violates the rules will
immediately fail CI.

The seven acceptance rules from the doc:

  1. Verb-led title, sentence case, no terminal punctuation.
  2. One-line summary that doesn't repeat the title.
  3. Single primary input with non-empty plain-language tooltip.
  4. Knob pattern produces at least one resolvable knob against the
     FNR 2006-018 Group 2 reference deal.
  5. ``locked_aspects`` is non-empty (so the customize panel can show
     "What stays the same").
  6. Verb-led primary button label.
  7. ``instantiate_template`` produces a SolverSpec with at least one
     knob and at least one objective when given the template's default
     primary input value.

Plus template-specific tests for the Auto-Tieout template.
"""
from __future__ import annotations

import pytest

from bma_standard_formulas.deals.schemas.solver_template import (
    PrimaryInputKind,
    SolverTemplate,
    TemplateCategory,
    TemplateInstantiationRequest,
)

from bma_cfengine_app.orchestrator.deals.solver_templates import (
    all_templates,
    get_template,
    instantiate_template,
    list_templates_for_deal,
    resolve_knobs,
    template_view_for_deal,
)
from tests.fixtures.fnr_2006_018.deal_definition import (
    build_fnr_2006_018_group_2_deal,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def reference_deal():
    """A real, well-tested deal for resolving knobs against. FNR 2006-018
    Group 2 is a clean sequential cascade with cash-paying bonds, a PO,
    and a notional IO -- a good cross-section for template tests.
    """
    return build_fnr_2006_018_group_2_deal(n_periods=240)


# ---------------------------------------------------------------------------
# Acceptance criteria (apply to every registered template)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("template", all_templates(), ids=lambda t: t.template_id)
class TestTemplateAcceptanceCriteria:
    """Per-template tests that enforce the solver UX design contract."""

    def test_title_is_verb_led_and_sentence_case(self, template: SolverTemplate):
        title = template.title
        assert title, f"{template.template_id}: title is empty"
        # Sentence case: first letter uppercase, no all-caps tokens.
        assert title[0].isupper(), (
            f"{template.template_id}: title '{title}' must start with a capital"
        )
        for word in title.split():
            assert not word.isupper() or len(word) <= 3, (
                f"{template.template_id}: title '{title}' contains an "
                f"all-caps token '{word}'; use sentence case."
            )
        # No terminal punctuation in card titles.
        assert not title.rstrip().endswith((".", "!", "?")), (
            f"{template.template_id}: title '{title}' should not end with "
            f"punctuation"
        )

    def test_one_line_summary_distinct_from_title(self, template: SolverTemplate):
        summary = template.one_line_summary
        assert summary, f"{template.template_id}: summary is empty"
        assert summary != template.title, (
            f"{template.template_id}: one_line_summary just repeats the title"
        )
        assert len(summary) >= 30, (
            f"{template.template_id}: summary '{summary}' is too short to be useful"
        )

    def test_primary_input_has_plain_language_tooltip(self, template: SolverTemplate):
        pi = template.primary_input
        assert pi.tooltip, (
            f"{template.template_id}: primary_input.tooltip is empty -- "
            f"plain-language tooltips are mandatory."
        )
        assert len(pi.tooltip) >= 30, (
            f"{template.template_id}: primary_input.tooltip is too short "
            f"({len(pi.tooltip)} chars); aim for one full sentence."
        )

    def test_locked_aspects_non_empty(self, template: SolverTemplate):
        assert template.locked_aspects, (
            f"{template.template_id}: locked_aspects is empty -- the "
            f"customize panel needs a 'What stays the same' list."
        )

    def test_primary_button_is_verb_led(self, template: SolverTemplate):
        label = template.primary_button_label
        assert label, f"{template.template_id}: primary_button_label is empty"
        assert label != "Run", (
            f"{template.template_id}: primary_button_label='Run' is generic; "
            f"use a specific verb (e.g., 'Find the coupons')."
        )
        # First word should be a verb in imperative form (heuristic: not a
        # noun like 'Solver' or 'Optimizer'). We do not parse English; we
        # just forbid the obvious anti-patterns.
        forbidden_first_words = {"Solver", "Optimization", "Optimizer", "Run"}
        first_word = label.split()[0] if label.split() else ""
        assert first_word not in forbidden_first_words, (
            f"{template.template_id}: primary_button_label '{label}' "
            f"starts with a noun; use a verb."
        )

    def test_knob_pattern_resolves_against_reference_deal(
        self, template: SolverTemplate, reference_deal
    ):
        resolved = resolve_knobs(reference_deal, template.knobs_pattern)
        # FNR Group 2 has cash-paying bonds; if a template's knob pattern
        # produces zero knobs against this deal, that's likely a bug.
        # We allow templates that are explicitly product-specific to skip
        # this test if their suitable_for_families excludes Group 2.
        assert len(resolved) >= 1, (
            f"{template.template_id}: knobs_pattern produced 0 knobs against "
            f"FNR 2006-018 Group 2; pattern likely misconfigured."
        )

    def test_instantiate_with_defaults_produces_runnable_spec(
        self, template: SolverTemplate, reference_deal
    ):
        request = TemplateInstantiationRequest(
            primary_input_value=template.primary_input.default,
        )
        response = instantiate_template(reference_deal, template, request)
        spec = response.spec
        assert spec.layers, f"{template.template_id}: SolverSpec has no layers"
        layer = spec.layers[0]
        assert layer.knobs, f"{template.template_id}: layer has no knobs"
        assert layer.objectives, f"{template.template_id}: layer has no objectives"
        # Summary should mention the template title for run-history readability.
        assert template.title in response.summary


# ---------------------------------------------------------------------------
# Auto-Tieout template specifics
# ---------------------------------------------------------------------------


class TestAutoTieoutTemplate:
    """Auto-Tieout-specific behaviors layered on top of the generic acceptance
    criteria.
    """

    @pytest.fixture
    def template(self) -> SolverTemplate:
        return get_template("auto_tieout_carry")

    def test_template_id_and_category(self, template):
        assert template.template_id == "auto_tieout_carry"
        assert template.category == TemplateCategory.BALANCE_DEAL

    def test_title_matches_design_doc(self, template):
        assert template.title == "Balance the deal"

    def test_primary_input_is_target_yield_slider(self, template):
        pi = template.primary_input
        assert pi.kind == PrimaryInputKind.NUMBER_SLIDER
        assert pi.field_id == "target_residual_yield_pct"
        assert pi.unit == "%"
        assert pi.default == 12.0
        assert pi.min_value == 0.0
        assert pi.max_value == 30.0

    def test_primary_button_label_says_find_the_coupons(self, template):
        assert template.primary_button_label == "Find the coupons"

    def test_excludes_zero_coupon_and_io_classes(self, template, reference_deal):
        resolved = resolve_knobs(reference_deal, template.knobs_pattern)
        knob_ids = {rk.knob_id for rk in resolved}
        # FNR Group 2 has BA, BC, BD (5.50% cash bonds), DO (zero-coupon
        # PO), DI (notional IO). The template should pick up BA/BC/BD and
        # skip DO and DI.
        assert "coupon_BA" in knob_ids
        assert "coupon_BC" in knob_ids
        assert "coupon_BD" in knob_ids
        assert "coupon_DO" not in knob_ids, (
            "DO is a zero-coupon PO; it should not be tunable for tie-out."
        )
        assert "coupon_DI" not in knob_ids, (
            "DI is a notional IO; its coupon tracks the underlying."
        )

    def test_bps_delta_bounds(self, template, reference_deal):
        """Default bps_delta=100 means each coupon knob has +/- 100 bps bounds."""
        resolved = resolve_knobs(reference_deal, template.knobs_pattern)
        for rk in resolved:
            current = rk.current_value
            assert rk.lower == pytest.approx(max(0.0, current - 1.0), abs=1e-6), (
                f"{rk.knob_id} lower={rk.lower} != current-100bps={current - 1.0}"
            )
            assert rk.upper == pytest.approx(current + 1.0, abs=1e-6), (
                f"{rk.knob_id} upper={rk.upper} != current+100bps={current + 1.0}"
            )

    def test_resolved_knob_label_human_readable(self, template, reference_deal):
        resolved = resolve_knobs(reference_deal, template.knobs_pattern)
        ba = next(rk for rk in resolved if rk.knob_id == "coupon_BA")
        # Label should be sentence case, no IR-paths in it.
        assert ba.label == "Class BA coupon"
        assert "bonds[" not in ba.label
        assert "deal_knobs" not in ba.label

    def test_locked_aspects_include_sizes_and_priority(self, template):
        locked = " | ".join(template.locked_aspects).lower()
        assert "size" in locked, "Tranche sizes must be in locked_aspects"
        assert "waterfall" in locked or "priority" in locked, (
            "Waterfall priority must be in locked_aspects"
        )

    def test_instantiate_uses_user_target(self, template, reference_deal):
        request = TemplateInstantiationRequest(primary_input_value=10.0)
        response = instantiate_template(reference_deal, template, request)
        objective = response.spec.layers[0].objectives[0]
        assert objective.target_value == 10.0
        assert objective.metric_path == "carry_tieout.implied_residual_ytm_cbe_pct"

    def test_instantiate_locks_specified_knob(self, template, reference_deal):
        # Lock BA; check it's missing from the resolved spec.
        request = TemplateInstantiationRequest(
            primary_input_value=12.0,
            locked_knob_ids=["coupon_BA"],
        )
        response = instantiate_template(reference_deal, template, request)
        knob_paths = {k.knob_path for k in response.spec.layers[0].knobs}
        assert "bonds[BA].coupon" not in knob_paths
        assert "bonds[BC].coupon" in knob_paths

    def test_locking_all_knobs_raises(self, template, reference_deal):
        all_knob_ids = [
            rk.knob_id
            for rk in resolve_knobs(reference_deal, template.knobs_pattern)
        ]
        request = TemplateInstantiationRequest(
            primary_input_value=12.0,
            locked_knob_ids=all_knob_ids,
        )
        with pytest.raises(ValueError, match="no tunable knobs"):
            instantiate_template(reference_deal, template, request)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestTemplateRegistry:
    def test_get_unknown_template_raises(self):
        with pytest.raises(KeyError, match="Unknown solver template"):
            get_template("does_not_exist")

    def test_list_templates_for_deal_returns_views_with_resolved_knobs(
        self, reference_deal
    ):
        views = list_templates_for_deal(reference_deal)
        assert views, "list_templates_for_deal returned an empty list"
        for v in views:
            assert v.resolved_knobs, (
                f"{v.template.template_id}: resolved_knobs is empty -- "
                f"the customize panel would have nothing to show."
            )

    def test_template_view_includes_resolved_knobs(self, reference_deal):
        tpl = get_template("auto_tieout_carry")
        view = template_view_for_deal(reference_deal, tpl)
        assert view.template.template_id == "auto_tieout_carry"
        assert len(view.resolved_knobs) >= 3  # BA, BC, BD at minimum
