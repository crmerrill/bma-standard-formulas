"""DealRunInput schemas — collateral cashflow inputs to the waterfall engine.

Two families of collateral inputs coexist:

LDCMA-format (POOLED / GROUPED / STRIP_PI variants):
    Period-keyed dict-of-arrays matching the LDCMA ``collCF`` convention.
    Built by the legacy adapters (``from_collateral_dict``,
    ``from_actual_cashflow``, ``from_portfolio_cashflow``,
    ``from_grouped_portfolio_cashflows``).  Suitable for parity testing
    against legacy LDCMA fixtures and for the bridge path that reads
    aggregate / per-group artifacts from disk.

PAIRED-format (proposal R, Phase 1):
    ``PortfolioCashflow`` in PAIRED mode held directly on the input
    payload, consumed natively by the runtime with full per-loan visibility
    (each constituent retains its ``group_id``, ``loan_id``, and per-period
    BMA-native arrays).  Multi-group deals tag each loan with ``group_id``
    and the runtime routes ``GROUP_<id>_*`` source tokens via
    ``portfolio.aggregate_actual_by_group()``.

The design intent is for PAIRED to become the canonical primary input form
while LDCMA-format remains for parity testing — see the design doc
``docs/architecture/waterfall_ir_design.md`` proposal R.
"""
from typing import Annotated, Any, Literal, Union

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

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
# Paired (BMA-native) input
# ---------------------------------------------------------------------------


class PairedCollateralInput(BaseModel):
    """Direct BMA PortfolioCashflow input — proposal R Phase 1.

    Wraps a ``bma_standard_formulas.engine.PortfolioCashflow`` so the
    deal runtime can consume the payload natively without going through
    the LDCMA-format adapter chain:

      - Whole-pool aggregate fields come from ``portfolio.pool``
        (``BMAActualCashflow``). Required.
      - Whole-pool scheduled stream comes from ``portfolio.scheduled``
        (``BMAScheduledCashflow``) when present (PAIRED mode) — used for
        scheduled-vs-actual decompositions in outputs and for PAC/TAC
        schedule re-derivation. Optional: ACTUAL_ONLY portfolios have no
        scheduled stream and the runtime degrades gracefully.
      - Per-group aggregates come from
        ``portfolio.aggregate_actual_by_group()`` and
        ``aggregate_scheduled_by_group()`` (Phase 0A primitives), keyed by
        ``str(loan.group_id)``. Multi-group deals tag each loan with its
        group_id; the runtime routes ``GROUP_<id>_*`` source tokens to the
        matching aggregate.
      - Per-loan resolution (Phase 1d) is available via
        ``portfolio.actual_constituents()`` for triggers, calculations,
        and per-loan analytics.

    Accepted PortfolioMode values:

      - ``PAIRED`` — has both scheduled and actual per loan. Full
        runtime fidelity (PAC/TAC re-derivation, scheduled-vs-actual,
        per-loan visibility).
      - ``ACTUAL_ONLY`` — actual cashflows only, no scheduled stream.
        Used by the ``ldcma_to_paired`` parity-testing adapter (Phase 1e)
        to route legacy LDCMA fixtures through the PAIRED runtime branch.
        Scheduled-stream consumers see ``None``; the loans accessor still
        works.

      ``SCHEDULED_ONLY`` is rejected — the runtime requires actual
      cashflow data via ``portfolio.pool``.

    Pydantic note: the underlying PortfolioCashflow is not a Pydantic model
    (it's a mutable engine object holding numpy arrays). The schema accepts
    it via ``arbitrary_types_allowed`` and the runtime treats it as an
    opaque handle. Serializing a DealRunInput with PAIRED mode through
    JSON is therefore not supported — the input is only meaningful for
    in-process runs from the engine.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    mode: Literal[CollateralInputMode.PAIRED] = CollateralInputMode.PAIRED
    portfolio: Any  # bma_standard_formulas.engine.PortfolioCashflow

    @model_validator(mode="after")
    def _validate_portfolio(self) -> "PairedCollateralInput":
        # Lazy import to avoid a circular dependency between schemas and engine.
        from bma_standard_formulas.engine import PortfolioCashflow
        from bma_standard_formulas.engine.portfolio import PortfolioMode

        if not isinstance(self.portfolio, PortfolioCashflow):
            raise TypeError(
                f"PairedCollateralInput.portfolio must be a PortfolioCashflow, "
                f"got {type(self.portfolio).__name__}"
            )
        if self.portfolio.mode == PortfolioMode.SCHEDULED_ONLY:
            raise ValueError(
                "PairedCollateralInput rejects SCHEDULED_ONLY portfolios — "
                "the deal runtime requires actual cashflow data via "
                "portfolio.pool. Use PortfolioMode.PAIRED (full fidelity) "
                "or PortfolioMode.ACTUAL_ONLY (no scheduled stream, used by "
                "the ldcma_to_paired parity adapter)."
            )
        return self


# ---------------------------------------------------------------------------
# Discriminated union
# ---------------------------------------------------------------------------

CollateralInput = Annotated[
    Union[
        PooledCollateralInput,
        GroupedCollateralInput,
        StripCollateralInput,
        PairedCollateralInput,
    ],
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
