"""Solver input contracts — objectives, constraints, knob bounds, and specs."""
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ObjectiveType(str, Enum):
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"
    TARGET = "TARGET"


class ConstraintComparison(str, Enum):
    GE = "GE"
    LE = "LE"
    EQ = "EQ"
    BETWEEN = "BETWEEN"


class WaterfallTargetPrimitive(str, Enum):
    """Domain-native waterfall target families for credit/CRT optimization."""

    CUM_LOSS_MULTIPLE_GAP = "CUM_LOSS_MULTIPLE_GAP"
    NO_SHORTFALL_INTEREST = "NO_SHORTFALL_INTEREST"
    NO_SHORTFALL_PRINCIPAL = "NO_SHORTFALL_PRINCIPAL"
    OC_IC_TRIGGER_RESILIENCE = "OC_IC_TRIGGER_RESILIENCE"
    STEPDOWN_ELIGIBILITY_SAFETY = "STEPDOWN_ELIGIBILITY_SAFETY"
    SUBORDINATION_FLOOR_GAP = "SUBORDINATION_FLOOR_GAP"
    RESERVE_SUFFICIENCY_GAP = "RESERVE_SUFFICIENCY_GAP"
    CE_TARGET_DELTA = "CE_TARGET_DELTA"
    PAC_SCHEDULE_MISS = "PAC_SCHEDULE_MISS"
    TAC_SCHEDULE_MISS = "TAC_SCHEDULE_MISS"
    Z_ACCRUAL_RELEASE_GAP = "Z_ACCRUAL_RELEASE_GAP"
    SUPPORT_BURNDOWN_GAP = "SUPPORT_BURNDOWN_GAP"


class KnobBound(BaseModel):
    """Bounds for a single solver knob (parameter to optimize)."""
    knob_path: str = Field(
        min_length=1,
        description="Dot-path into DealDefinition or deal_knobs, "
                    "e.g. 'bonds[A].coupon' or 'deal_knobs.class_a_pctbal'",
    )
    lower: float
    upper: float
    initial: float | None = None
    step_hint: float | None = None


class ObjectiveSpec(BaseModel):
    """What the solver is trying to achieve."""
    name: str = Field(min_length=1)
    metric_path: str = Field(
        min_length=1,
        description="Path to the output metric, "
                    "e.g. 'tranche_risk_summary[A].yield_pct'",
    )
    objective_type: ObjectiveType = ObjectiveType.TARGET
    target_value: float | None = None
    weight: float = 1.0
    target_primitive: WaterfallTargetPrimitive | None = None
    primitive_params: dict[str, Any] = Field(default_factory=dict)


class ConstraintSpec(BaseModel):
    """A constraint the solver must satisfy."""
    name: str = Field(min_length=1)
    metric_path: str = Field(min_length=1)
    comparison: ConstraintComparison
    value: float | None = None
    lower: float | None = None
    upper: float | None = None
    tolerance: float = 1e-6
    hard: bool = True
    target_primitive: WaterfallTargetPrimitive | None = None
    primitive_params: dict[str, Any] = Field(default_factory=dict)


class SolverLayerSpec(BaseModel):
    """Configuration for one layer in a staged solver pipeline."""
    layer_name: str = Field(min_length=1)
    objectives: list[ObjectiveSpec] = Field(min_length=1)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    knobs: list[KnobBound] = Field(min_length=1)
    max_iterations: int = Field(default=100, ge=1)
    convergence_tolerance: float = 1e-4
    warm_start_from_prior: bool = True


class SolverSpec(BaseModel):
    """Top-level solver specification — one or more staged layers."""
    solver_name: str = Field(min_length=1)
    layers: list[SolverLayerSpec] = Field(min_length=1)
    checkpoint_every_n: int = Field(default=10, ge=1)
    global_max_iterations: int = Field(default=500, ge=1)
    description: str = ""
