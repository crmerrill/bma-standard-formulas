"""Waterfall primitive operations — deterministic, side-effect-explicit cash movement.

Each op mutates the workspace arrays in-place and returns the payment amount.
The workspace is an internal mutable buffer; external inputs are read-only.
All ops correspond to LDCMA deal.py primitives (payinterest, payprincipal, etc.)
re-expressed as pure functions on typed workspace arrays.
"""
import numpy as np


def available_cash(sources: list[float]) -> float:
    """Minimum cash across all source accounts (LDCMA ``cashfromacct``)."""
    if not sources:
        return float("inf")
    return min(sources)


def _source_min(source_balances: list[np.ndarray], i: int) -> float:
    """Fast minimum across source arrays at index i — no isinstance checks."""
    if not source_balances:
        return float("inf")
    mn = source_balances[0][i]
    for k in range(1, len(source_balances)):
        v = source_balances[k][i]
        if v < mn:
            mn = v
    return mn


def _debit_sources(source_balances: list[np.ndarray], i: int, pmt: float) -> None:
    """Subtract payment from all source arrays at index i."""
    for s in source_balances:
        s[i] -= pmt


def pay_interest(
    source_balances: list[np.ndarray],
    bond_interest: np.ndarray,
    bond_opt_interest: np.ndarray,
    bond_int_shortfall: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
    shortfall: bool = False,
    allow_negative: bool = False,
) -> float:
    target = bond_int_shortfall if shortfall else bond_opt_interest
    cash = _source_min(source_balances, i)
    pmt = min(cash, target[i])
    if max_amount is not None:
        pmt = min(pmt, max_amount)
    if pmt <= 0.0 and not allow_negative:
        return 0.0
    bond_interest[i] += pmt
    target[i] -= pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_principal(
    source_balances: list[np.ndarray],
    bond_principal: np.ndarray,
    bond_balance: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
    allow_negative: bool = False,
) -> float:
    cash = _source_min(source_balances, i)
    pmt = min(cash, bond_balance[i])
    if max_amount is not None:
        pmt = min(pmt, max_amount)
    if pmt <= 0.0 and not allow_negative:
        return 0.0
    bond_principal[i] += pmt
    bond_balance[i] -= pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_writedown(
    source_balances: list[np.ndarray],
    bond_writedown: np.ndarray,
    bond_balance: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
    allow_negative: bool = False,
) -> float:
    cash = _source_min(source_balances, i)
    pmt = min(cash, bond_balance[i])
    if max_amount is not None:
        pmt = min(pmt, max_amount)
    if pmt <= 0.0 and not allow_negative:
        return 0.0
    bond_writedown[i] += pmt
    bond_balance[i] -= pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_fee(
    source_balances: list[np.ndarray],
    fee_interest: np.ndarray,
    i: int,
    amount: float,
    *,
    allow_negative: bool = False,
) -> float:
    cash = _source_min(source_balances, i)
    pmt = min(cash, amount)
    if pmt <= 0.0 and not allow_negative:
        return 0.0
    fee_interest[i] += pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_residual(
    source_balances: list[np.ndarray],
    resid_interest: np.ndarray,
    i: int,
    amount: float | None = None,
    *,
    allow_negative: bool = False,
) -> float:
    cash = _source_min(source_balances, i)
    pmt = min(cash, amount) if amount is not None else max(0.0, cash)
    if pmt <= 0.0 and not allow_negative:
        return 0.0
    resid_interest[i] += pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_to_reserve(
    source_balances: list[np.ndarray],
    reserve_balance: np.ndarray,
    reserve_principal: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
) -> float:
    cash = _source_min(source_balances, i)
    pmt = min(cash, max_amount) if max_amount is not None else max(0.0, cash)
    if pmt <= 0.0:
        return 0.0
    reserve_balance[i] += pmt
    reserve_principal[i] -= pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_interest_from_reserve(
    source_balances: list[np.ndarray],
    bond_interest: np.ndarray,
    bond_opt_interest: np.ndarray,
    bond_int_shortfall: np.ndarray,
    reserve_balance: np.ndarray,
    reserve_principal: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
    shortfall: bool = False,
) -> float:
    target = bond_int_shortfall if shortfall else bond_opt_interest
    cash_limit = _source_min(source_balances, i) if source_balances else float("inf")
    pmt = min(reserve_balance[i], target[i])
    if max_amount is not None:
        pmt = min(pmt, max_amount)
    pmt = min(pmt, cash_limit)
    if pmt <= 0.0:
        return 0.0
    bond_interest[i] += pmt
    target[i] -= pmt
    reserve_balance[i] -= pmt
    reserve_principal[i] += pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_principal_from_reserve(
    source_balances: list[np.ndarray],
    bond_principal: np.ndarray,
    bond_balance: np.ndarray,
    reserve_balance: np.ndarray,
    reserve_principal: np.ndarray,
    i: int,
    *,
    max_amount: float | None = None,
) -> float:
    cash_limit = _source_min(source_balances, i) if source_balances else float("inf")
    pmt = min(reserve_balance[i], bond_balance[i])
    if max_amount is not None:
        pmt = min(pmt, max_amount)
    pmt = min(pmt, cash_limit)
    if pmt <= 0.0:
        return 0.0
    bond_principal[i] += pmt
    bond_balance[i] -= pmt
    reserve_balance[i] -= pmt
    reserve_principal[i] += pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_from_reserve(
    source_balances: list[np.ndarray],
    bond_interest: np.ndarray,
    reserve_balance: np.ndarray,
    reserve_principal: np.ndarray,
    i: int,
    amount: float | None = None,
) -> float:
    cash_limit = _source_min(source_balances, i) if source_balances else float("inf")
    pmt = min(reserve_balance[i], amount) if amount is not None else reserve_balance[i]
    pmt = min(pmt, cash_limit)
    if pmt <= 0.0:
        return 0.0
    bond_interest[i] += pmt
    reserve_balance[i] -= pmt
    reserve_principal[i] += pmt
    _debit_sources(source_balances, i, pmt)
    return pmt


def pay_recourse_interest(
    from_bond_principal: np.ndarray,
    from_bond_balance: np.ndarray,
    to_bond_interest: np.ndarray,
    to_bond_opt_interest: np.ndarray,
    to_bond_int_shortfall: np.ndarray,
    i: int,
    *,
    shortfall: bool = False,
) -> float:
    target = to_bond_int_shortfall if shortfall else to_bond_opt_interest
    pmt = max(0.0, target[i])
    to_bond_interest[i] += pmt
    target[i] -= pmt
    from_bond_principal[i] -= pmt
    from_bond_balance[i] += pmt
    return pmt


def pay_recourse_principal(
    from_bond_principal: np.ndarray,
    from_bond_balance: np.ndarray,
    to_bond_principal: np.ndarray,
    to_bond_balance: np.ndarray,
    i: int,
    amount: float,
) -> float:
    pmt = max(0.0, amount)
    to_bond_principal[i] += pmt
    to_bond_balance[i] -= pmt
    from_bond_principal[i] -= pmt
    from_bond_balance[i] += pmt
    return pmt


# ---------------------------------------------------------------------------
# Bond update functions — accept BondWorkspace directly (no dict bridge)
# ---------------------------------------------------------------------------


def update_bonds_pre_ws(bonds: dict, i: int) -> None:
    """Pre-waterfall: compute optimal interest, carry balances forward.

    Accepts dict[str, BondWorkspace] — operates on attributes directly.
    """
    for ws in bonds.values():
        if ws.is_bond:
            ws.opt_interest[i] = ws.balance[i - 1] * ws.opt_coupons[i] / 1200.0
        ws.balance[i] = ws.balance[i - 1]
        ws.int_shortfall[i] = ws.int_shortfall[i - 1]


def update_bonds_post_ws(bonds: dict, i: int) -> None:
    """Post-waterfall: accumulate shortfalls and update tracking bonds.

    Accepts dict[str, BondWorkspace] — operates on attributes directly.
    """
    for ws in bonds.values():
        if ws.is_bond:
            ws.int_shortfall[i] += max(0.0, ws.opt_interest[i])
        if ws.tracks_bonds:
            for attr, tracked_names in ws.tracks_bonds.items():
                getattr(ws, attr)[i] = sum(
                    getattr(bonds[tn], attr)[i] for tn in tracked_names
                )


def finalize_bond_ws(ws, is_pseudo: bool, is_bond: bool) -> None:
    """Post-run finalization on a BondWorkspace — no dict wrapping needed."""
    balance = ws.balance
    interest = ws.interest
    principal = ws.principal
    coupons = ws.coupons
    writedown = ws.writedown
    cashflow = ws.cashflow

    n = len(balance)
    for i in range(1, n):
        if not is_pseudo:
            if balance[i - 1] > 0:
                coupons[i] = interest[i] / balance[i - 1] * 1200.0
        if is_pseudo or is_bond:
            cashflow[i] = principal[i] + interest[i]


# Keep legacy dict-based functions for backward compat (used by external callers)
def update_bonds_pre(bonds: dict[str, dict[str, np.ndarray]], i: int) -> None:
    for name, ws in bonds.items():
        if ws.get("is_bond", False):
            ws["opt_interest"][i] = ws["balance"][i - 1] * ws["opt_coupons"][i] / 1200.0
        ws["balance"][i] = ws["balance"][i - 1]
        ws["int_shortfall"][i] = ws["int_shortfall"][i - 1]


def update_bonds_post(bonds: dict[str, dict[str, np.ndarray]], i: int) -> None:
    for name, ws in bonds.items():
        if ws.get("is_bond", False):
            ws["int_shortfall"][i] += max(0.0, ws["opt_interest"][i])
        tracks = ws.get("tracks_bonds")
        if tracks:
            for attr, tracked_names in tracks.items():
                ws[attr][i] = sum(bonds[tn][attr][i] for tn in tracked_names)


def finalize_bond(ws: dict[str, np.ndarray], is_pseudo: bool, is_bond: bool) -> None:
    balance = ws["balance"]
    interest = ws["interest"]
    principal = ws["principal"]
    coupons = ws["coupons"]
    writedown = ws["writedown"]
    cashflow = ws["cashflow"]
    n = len(balance)
    for i in range(1, n):
        if not is_pseudo:
            if balance[i - 1] > 0:
                coupons[i] = interest[i] / balance[i - 1] * 1200.0
        if is_pseudo or is_bond:
            cashflow[i] = principal[i] + interest[i]
