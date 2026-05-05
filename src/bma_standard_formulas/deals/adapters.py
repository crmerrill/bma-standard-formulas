"""Collateral input adapters — bridge BMA engine outputs to DealRunInput.

Adapters convert:
- PortfolioCashflow / BMAActualCashflow → PooledCollateralInput
- Multiple PortfolioCashflows (grouped) → GroupedCollateralInput
- P/I strip arrays → StripCollateralInput
"""
from datetime import date
from typing import Any

import numpy as np

from .schemas.common import CollateralInputMode
from .schemas.input import (
    CollateralCashflows,
    DealRunInput,
    GroupedCollateralInput,
    PooledCollateralInput,
    StripCollateralInput,
)


def _zeros_like(arr: np.ndarray) -> list[float]:
    return [0.0] * len(arr)


def _to_list(arr: Any) -> list[float]:
    if isinstance(arr, np.ndarray):
        return arr.tolist()
    if isinstance(arr, list):
        return [float(x) for x in arr]
    return list(arr)


def _build_cf_from_dict(cf_dict: dict[str, Any], n: int) -> CollateralCashflows:
    """Build CollateralCashflows from a dict of arrays (LDCMA-style)."""

    def _get(key: str) -> list[float]:
        val = cf_dict.get(key)
        if val is None:
            return [0.0] * n
        return _to_list(val)

    return CollateralCashflows(
        cfdate=cf_dict.get("cfdate", list(range(n))),
        balance=_get("balance"),
        principal=_get("principal"),
        interest=_get("interest"),
        cashflow=_get("cashflow"),
        loss=_get("loss"),
        prepbal=_get("prepbal"),
        defbal=_get("defbal"),
        recovery=_get("recovery"),
        principal_sched=_get("principal_sched"),
        principal_unsched=_get("principal_unsched"),
        cpr=_get("cpr"),
        cdr=_get("cdr"),
        sev=_get("sev"),
        dq=_get("dq"),
        surv_fac=_get("surv_fac"),
        sched_coupon=_get("sched_coupon"),
        sched_netcoupon=_get("sched_netcoupon"),
        coupon=_get("coupon"),
        effcoupon=_get("effcoupon"),
        sched_balance=_get("sched_balance"),
        discount_factor=_get("discount_factor"),
    )


def from_collateral_dict(
    collcf: dict[str, dict[str, Any]],
    *,
    loan_count: int | None = None,
    market_date: str | None = None,
) -> DealRunInput:
    """Convert an LDCMA-style ``collCF`` dict to a DealRunInput.

    The LDCMA convention uses ``collCF['COLLAT']`` for the primary pool and
    optional ``collCF['COLLAT_*']`` keys for additional collateral groups.

    Args:
        collcf:      Dict keyed by group name (e.g. ``{'COLLAT': {...}}``)
        loan_count:  Number of loans in the pool.
        market_date: Market/settlement date string.

    Returns:
        DealRunInput with appropriate CollateralInput variant.
    """
    if len(collcf) == 1 and "COLLAT" in collcf:
        cf_data = collcf["COLLAT"]
        n = len(cf_data["balance"])
        cf = _build_cf_from_dict(cf_data, n)
        return DealRunInput(
            collateral=PooledCollateralInput(collateral=cf),
            loan_count=loan_count,
            original_collateral_balance=cf_data["balance"][0],
            market_date=market_date,
        )

    groups: dict[str, CollateralCashflows] = {}
    orig_bal = 0.0
    for gname, cf_data in collcf.items():
        n = len(cf_data["balance"])
        groups[gname] = _build_cf_from_dict(cf_data, n)
        orig_bal += cf_data["balance"][0]

    return DealRunInput(
        collateral=GroupedCollateralInput(groups=groups),
        loan_count=loan_count,
        original_collateral_balance=orig_bal,
        market_date=market_date,
    )


def _portfolio_df_to_cf_dict(portfolio_df: Any) -> tuple[dict[str, Any], int]:
    """Translate a BMA PortfolioCashflow-shaped DataFrame to an LDCMA-style cf_dict.

    Internal helper shared by :func:`from_portfolio_cashflow` and
    :func:`from_grouped_portfolio_cashflows`. Encapsulates the BMA → LDCMA
    field-name mapping so callers (single-pool vs multi-group) build the
    same dict shape from the same DataFrame columns.

    Args:
        portfolio_df: A pandas DataFrame with BMA engine output columns
            (perf_bal, act_am, vol_prepay, act_int, new_def, prin_recov,
            prin_loss; optionally gross_rate).

    Returns:
        A tuple ``(cf_dict, n)`` where ``cf_dict`` is in the shape expected
        by :func:`_build_cf_from_dict` and ``n`` is the period count.

    Raises:
        TypeError: If ``portfolio_df`` is not a pandas DataFrame.
    """
    import pandas as pd

    if not isinstance(portfolio_df, pd.DataFrame):
        raise TypeError(f"Expected DataFrame, got {type(portfolio_df)}")

    n = len(portfolio_df)
    cf_dict: dict[str, Any] = {
        "cfdate": list(range(n)),
        "balance": _to_list(portfolio_df.get("perf_bal", np.zeros(n))),
        "principal": _to_list(
            portfolio_df.get("act_am", np.zeros(n))
            + portfolio_df.get("vol_prepay", np.zeros(n))
        ),
        "interest": _to_list(portfolio_df.get("act_int", np.zeros(n))),
        "cashflow": _to_list(
            portfolio_df.get("act_am", np.zeros(n))
            + portfolio_df.get("vol_prepay", np.zeros(n))
            + portfolio_df.get("act_int", np.zeros(n))
        ),
        "loss": _to_list(portfolio_df.get("prin_loss", np.zeros(n))),
        "prepbal": _to_list(portfolio_df.get("vol_prepay", np.zeros(n))),
        "defbal": _to_list(portfolio_df.get("new_def", np.zeros(n))),
        "recovery": _to_list(portfolio_df.get("prin_recov", np.zeros(n))),
        "principal_sched": _to_list(portfolio_df.get("act_am", np.zeros(n))),
        "principal_unsched": _to_list(portfolio_df.get("vol_prepay", np.zeros(n))),
        "cpr": [0.0] * n,
        "cdr": [0.0] * n,
        "sev": [0.0] * n,
        "dq": [0.0] * n,
        "surv_fac": [1.0] * n,
        "sched_coupon": [0.0] * n,
        "sched_netcoupon": [0.0] * n,
        "coupon": [0.0] * n,
        "effcoupon": [0.0] * n,
        "sched_balance": _to_list(portfolio_df.get("perf_bal", np.zeros(n))),
        "discount_factor": [1.0] * n,
    }

    if "gross_rate" in portfolio_df.columns:
        cf_dict["coupon"] = _to_list(portfolio_df["gross_rate"])
        cf_dict["effcoupon"] = _to_list(portfolio_df["gross_rate"])

    return cf_dict, n


def from_portfolio_cashflow(
    portfolio_df: Any,
    *,
    loan_count: int | None = None,
    market_date: str | None = None,
) -> DealRunInput:
    """Convert a BMA PortfolioCashflow DataFrame to a single-pool DealRunInput.

    Maps BMA engine output columns to the LDCMA-style CollateralCashflows
    field names expected by the waterfall runtime, then wraps the result
    as a ``PooledCollateralInput``.
    """
    cf_dict, n = _portfolio_df_to_cf_dict(portfolio_df)
    cf = _build_cf_from_dict(cf_dict, n)
    orig_bal = float(cf_dict["balance"][0]) if n > 0 else 0.0

    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        loan_count=loan_count,
        original_collateral_balance=orig_bal,
        market_date=market_date,
    )


def from_grouped_portfolio_cashflows(
    group_dfs: dict[str, Any],
    *,
    loan_count: int | None = None,
    market_date: str | None = None,
) -> DealRunInput:
    """Convert per-group BMA PortfolioCashflow DataFrames to a multi-group DealRunInput.

    Each entry in ``group_dfs`` (keyed by ``group_id``) becomes one
    ``CollateralCashflows`` instance inside a ``GroupedCollateralInput``.
    The deal runtime then routes ``GROUP_<id>_*`` source tokens to the
    matching group's stream.

    The orchestrator (Phase 0B) emits per-group portfolio artifacts whose
    DataFrames have the same shape as the whole-pool aggregate; this adapter
    turns that on-disk representation into the runtime's grouped input form
    without re-running the engine.

    Args:
        group_dfs: Mapping ``group_id`` -> BMA-shaped DataFrame.  Group IDs
            are stringified consistently with
            :func:`_partition_by_group_id` and the deal IR's
            ``CollateralGroupDef.group_id``.
        loan_count: Total loan count across all groups (informational).
        market_date: Market / settlement date string (informational).

    Returns:
        DealRunInput with a ``GroupedCollateralInput`` collateral payload.

    Raises:
        ValueError: If ``group_dfs`` is empty.
    """
    if not group_dfs:
        raise ValueError("from_grouped_portfolio_cashflows requires at least one group")

    groups: dict[str, CollateralCashflows] = {}
    orig_bal = 0.0
    for gid, df in group_dfs.items():
        cf_dict, n = _portfolio_df_to_cf_dict(df)
        groups[str(gid)] = _build_cf_from_dict(cf_dict, n)
        if n > 0:
            orig_bal += float(cf_dict["balance"][0])

    return DealRunInput(
        collateral=GroupedCollateralInput(groups=groups),
        loan_count=loan_count,
        original_collateral_balance=orig_bal,
        market_date=market_date,
    )


def from_actual_cashflow(
    actual: Any,
    *,
    horizon: int | None = None,
    loan_count: int | None = None,
    market_date: str | None = None,
    initial_balance: float | None = None,
    discount_factors: Any = None,
    net_of_servicing: bool = False,
) -> DealRunInput:
    """Convert a BMA `actual_cashflow_from_loan` output to ``DealRunInput``.

    Mirrors :func:`from_portfolio_cashflow` (the production adapter that
    accepts a portfolio DataFrame artifact) but takes the typed
    ``BMAActualCashflow`` namedtuple-like object directly so callers that
    already have a result in memory (e.g. notebooks, parity harnesses, the
    FNR test fixture) avoid a DataFrame round-trip.

    Field mapping:

    ===========================  ================================
    BMA actual cashflow field    CollateralCashflows field
    ===========================  ================================
    ``perf_bal``                 ``balance``, ``sched_balance``
    ``act_am``                   ``principal_sched``
    ``vol_prepay``               ``principal_unsched``, ``prepbal``
    ``act_am + vol_prepay``      ``principal``
    ``act_int`` or               ``interest``  (gross, or net per
      ``act_int - svc_billed``               ``net_of_servicing``)
    ``new_def``                  ``defbal``
    ``prin_recov``               ``recovery``
    ``prin_loss``                ``loss``
    ===========================  ================================

    Servicing convention:

    BMA's ``act_int`` is the GROSS interest the loan delivers to whoever
    holds it (servicing fees are tracked separately as ``svc_billed``).
    Two architectural options for routing this into a deal:

    1. **Trust-layer fee**: pass ``net_of_servicing=False`` (default).
       The deal engine receives gross interest, and the deal IR models
       the servicing wedge as a `FeeDef` + `PAY_FEE` rule that deducts
       it before bond interest. Right for private-label deals where
       master servicer / trustee fees deduct at the trust waterfall.

    2. **MBS-layer netting** (e.g., Fannie Mae REMIC): pass
       ``net_of_servicing=True``. The adapter computes
       ``interest = act_int - svc_billed`` so the deal engine receives
       net pass-through interest directly, mirroring how each MBS pool
       delivers only the MBS pass-through rate to the REMIC trust
       (the Fannie Mae guaranty fee never enters the trust). The deal
       IR then has no wedge fee.

    Args:
        actual: ``BMAActualCashflow`` (or any object with the standard field
            names: ``perf_bal``, ``act_am``, ``vol_prepay``, ``act_int``,
            ``svc_billed`` (when ``net_of_servicing=True``), ``new_def``,
            ``prin_recov``, ``prin_loss``).
        horizon: Optional truncation length. If ``None``, uses the full
            length of the actual-cashflow arrays.
        loan_count: Number of loans in the underlying pool.
        market_date: Market/settlement date string.
        initial_balance: Optional override for the deal's
            ``original_collateral_balance``. Defaults to ``perf_bal[0]``.
        discount_factors: Optional sequence of per-period discount factors
            (length matches horizon). Defaults to ones.
        net_of_servicing: When True, deduct ``svc_billed`` from ``act_int``
            so the deal engine receives net pass-through interest. Use for
            MBS-backed REMICs where the wedge is netted at the MBS layer.

    Returns:
        DealRunInput with PooledCollateralInput populated.
    """
    perf_bal = np.asarray(actual.perf_bal, dtype=float)
    act_am = np.asarray(actual.act_am, dtype=float)
    vol_prepay = np.asarray(actual.vol_prepay, dtype=float)
    act_int = np.asarray(actual.act_int, dtype=float)
    new_def = np.asarray(actual.new_def, dtype=float)
    prin_recov = np.asarray(actual.prin_recov, dtype=float)
    prin_loss = np.asarray(actual.prin_loss, dtype=float)

    full_len = len(perf_bal)
    n = full_len if horizon is None else min(int(horizon), full_len)

    principal = (act_am[:n] + vol_prepay[:n]).astype(float)
    if net_of_servicing:
        svc_billed = np.asarray(getattr(actual, "svc_billed", np.zeros(full_len)),
                                dtype=float)
        interest = (act_int[:n] - svc_billed[:n]).astype(float)
    else:
        interest = act_int[:n].astype(float)
    balance = perf_bal[:n].astype(float)

    if discount_factors is None:
        df_arr = [1.0] * n
    else:
        df_arr = [float(x) for x in discount_factors[:n]]

    cf = CollateralCashflows(
        cfdate=list(range(n)),
        balance=balance.tolist(),
        principal=principal.tolist(),
        interest=interest.tolist(),
        cashflow=(principal + interest).tolist(),
        loss=prin_loss[:n].tolist(),
        prepbal=vol_prepay[:n].tolist(),
        defbal=new_def[:n].tolist(),
        recovery=prin_recov[:n].tolist(),
        principal_sched=act_am[:n].tolist(),
        principal_unsched=vol_prepay[:n].tolist(),
        cpr=[0.0] * n,
        cdr=[0.0] * n,
        sev=[0.0] * n,
        dq=[0.0] * n,
        surv_fac=[1.0] * n,
        sched_coupon=[0.0] * n,
        sched_netcoupon=[0.0] * n,
        coupon=[0.0] * n,
        effcoupon=[0.0] * n,
        sched_balance=balance.tolist(),
        discount_factor=df_arr,
    )

    orig_bal = (
        float(initial_balance)
        if initial_balance is not None
        else (float(balance[0]) if n > 0 else 0.0)
    )

    return DealRunInput(
        collateral=PooledCollateralInput(collateral=cf),
        loan_count=loan_count,
        original_collateral_balance=orig_bal,
        market_date=market_date,
    )


def from_pi_strips(
    principal_arrays: dict[str, Any],
    interest_arrays: dict[str, Any],
    *,
    loan_count: int | None = None,
    market_date: str | None = None,
) -> DealRunInput:
    """Build DealRunInput from separate P and I strip array dicts."""
    n_p = len(principal_arrays.get("balance", []))
    n_i = len(interest_arrays.get("balance", []))
    n = max(n_p, n_i)

    p_cf = _build_cf_from_dict(principal_arrays, n)
    i_cf = _build_cf_from_dict(interest_arrays, n)

    orig_bal = principal_arrays.get("balance", [0.0])[0] if n > 0 else 0.0

    return DealRunInput(
        collateral=StripCollateralInput(
            principal_strip=p_cf,
            interest_strip=i_cf,
        ),
        loan_count=loan_count,
        original_collateral_balance=orig_bal,
        market_date=market_date,
    )
