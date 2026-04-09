"""DealRunInput schemas — collateral cashflow inputs to the waterfall engine."""
from typing import Annotated, Literal, Union

import numpy as np
from pydantic import BaseModel, Field, model_validator

from .common import CollateralInputMode, Dollars, SchemaMetadata


# ---------------------------------------------------------------------------
# Collateral cashflow arrays (dict-of-arrays, matching LDCMA convention)
# ---------------------------------------------------------------------------


class CollateralCashflows(BaseModel):
    """Period-indexed collateral cashflow arrays for a single collateral group.

    All arrays must have the same length (number of periods including period 0).
    Field names align with the LDCMA ``collCF['COLLAT']`` dict keys and BMA
    engine outputs so adapters can bridge without transformation.
    """
    model_config = {"arbitrary_types_allowed": True}

    cfdate: list = Field(description="Payment dates per period")
    balance: list[float] = Field(min_length=1)
    principal: list[float]
    interest: list[float]
    cashflow: list[float]
    loss: list[float]
    prepbal: list[float]
    defbal: list[float]
    recovery: list[float]
    principal_sched: list[float]
    principal_unsched: list[float]
    cpr: list[float]
    cdr: list[float]
    sev: list[float]
    dq: list[float]
    surv_fac: list[float]
    sched_coupon: list[float]
    sched_netcoupon: list[float]
    coupon: list[float]
    effcoupon: list[float]
    sched_balance: list[float]
    discount_factor: list[float] | None = None

    @model_validator(mode="after")
    def _validate_lengths(self) -> "CollateralCashflows":
        n = len(self.balance)
        for fname in self.__class__.model_fields:
            val = getattr(self, fname)
            if isinstance(val, list) and fname != "cfdate":
                if len(val) != n:
                    raise ValueError(
                        f"Field {fname!r} has length {len(val)}, expected {n} "
                        f"(matching balance)"
                    )
        return self


# ---------------------------------------------------------------------------
# Pooled input
# ---------------------------------------------------------------------------


class PooledCollateralInput(BaseModel):
    """Single pooled collateral feed (standard case)."""
    mode: Literal[CollateralInputMode.POOLED] = CollateralInputMode.POOLED
    collateral: CollateralCashflows


# ---------------------------------------------------------------------------
# Grouped input
# ---------------------------------------------------------------------------


class GroupedCollateralInput(BaseModel):
    """Multiple named collateral groups feeding distinct waterfall branches."""
    mode: Literal[CollateralInputMode.GROUPED] = CollateralInputMode.GROUPED
    groups: dict[str, CollateralCashflows] = Field(min_length=1)


# ---------------------------------------------------------------------------
# P/I strip input
# ---------------------------------------------------------------------------


class StripCollateralInput(BaseModel):
    """Principal and interest strips as separate feeds."""
    mode: Literal[CollateralInputMode.STRIP_PI] = CollateralInputMode.STRIP_PI
    principal_strip: CollateralCashflows
    interest_strip: CollateralCashflows


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

CollateralInput = Annotated[
    Union[PooledCollateralInput, GroupedCollateralInput, StripCollateralInput],
    Field(discriminator="mode"),
]


# ---------------------------------------------------------------------------
# DealRunInput — everything needed to execute one waterfall run
# ---------------------------------------------------------------------------


class DealRunInput(BaseModel):
    """Complete input bundle for a single waterfall execution."""
    metadata: SchemaMetadata = Field(default_factory=SchemaMetadata)
    deal_definition_id: str | None = None
    collateral: CollateralInput
    loan_count: int | None = None
    original_collateral_balance: Dollars | None = None
    market_date: str | None = None
    deal_knob_overrides: dict[str, float] = Field(default_factory=dict)
