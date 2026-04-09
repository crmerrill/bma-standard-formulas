"""Waterfall runtime engine — executes a DealDefinition IR against collateral inputs.

The engine:
1. Allocates internal mutable workspace arrays from the immutable IR + input.
2. Pre-compiles the waterfall rules into a dispatch table (once per deal).
3. Runs the period loop calling pre-resolved function pointers.
4. Produces output bundles with deferred Pydantic construction.

External inputs (collateral arrays) are never mutated.
"""
from dataclasses import dataclass
from typing import Any

import numpy as np

from .ops import (
    finalize_bond_ws,
    pay_fee,
    pay_from_reserve,
    pay_interest,
    pay_interest_from_reserve,
    pay_principal,
    pay_principal_from_reserve,
    pay_residual,
    pay_to_reserve,
    pay_writedown,
    update_bonds_post_ws,
    update_bonds_pre_ws,
)
from .schemas.common import RuleType
from .schemas.input import (
    DealRunInput,
    GroupedCollateralInput,
    PooledCollateralInput,
    StripCollateralInput,
)
from .schemas.ir import DealDefinition
from .schemas.output_bond import BondCashflowRow
from .schemas.output_bundle import ScenarioOutputBundle
from .schemas.output_waterfall import WaterfallTraceRow


# ---------------------------------------------------------------------------
# Workspace — internal mutable state for one waterfall run
# ---------------------------------------------------------------------------

_RT = RuleType


@dataclass
class BondWorkspace:
    """Mutable workspace arrays for a single bond during execution."""
    name: str
    is_bond: bool
    is_pseudo: bool
    balance: np.ndarray
    principal: np.ndarray
    interest: np.ndarray
    opt_interest: np.ndarray
    opt_coupons: np.ndarray
    int_shortfall: np.ndarray
    coupons: np.ndarray
    cashflow: np.ndarray
    writedown: np.ndarray
    trigger_val: np.ndarray
    trigger_tgt: np.ndarray
    trigger_event: list
    xs_spread: np.ndarray
    xs_spread_cpn: np.ndarray
    tracks_bonds: dict[str, list[str]] | None = None


def _allocate_bond_workspace(
    bond_def,
    cf_len: int,
    collateral_balance_0: float,
) -> BondWorkspace:
    if bond_def.size_pct is not None and bond_def.size_pct > 0:
        initial_balance = collateral_balance_0 * bond_def.size_pct / 100.0
    elif bond_def.size_dollars is not None:
        initial_balance = bond_def.size_dollars
    else:
        initial_balance = 0.0

    balance = np.zeros(cf_len)
    balance[0] = initial_balance

    if bond_def.is_pseudo and not bond_def.is_bond:
        balance[:] = collateral_balance_0
        balance[0] = initial_balance if initial_balance > 0 else collateral_balance_0

    opt_coupons = np.zeros(cf_len)
    if bond_def.is_bond and not bond_def.is_pseudo:
        if bond_def.coupon_type.value == "FIXED" and bond_def.coupon is not None:
            opt_coupons[:] = bond_def.coupon

    return BondWorkspace(
        name=bond_def.name,
        is_bond=bond_def.is_bond and not bond_def.is_pseudo,
        is_pseudo=bond_def.is_pseudo,
        balance=balance,
        principal=np.zeros(cf_len),
        interest=np.zeros(cf_len),
        opt_interest=np.zeros(cf_len),
        opt_coupons=opt_coupons,
        int_shortfall=np.zeros(cf_len),
        coupons=np.zeros(cf_len),
        cashflow=np.zeros(cf_len),
        writedown=np.zeros(cf_len),
        trigger_val=np.zeros(cf_len),
        trigger_tgt=np.zeros(cf_len),
        trigger_event=[""] * cf_len,
        xs_spread=np.zeros(cf_len),
        xs_spread_cpn=np.zeros(cf_len),
        tracks_bonds=bond_def.tracks_bonds,
    )


# ---------------------------------------------------------------------------
# Pre-compiled dispatch table
# ---------------------------------------------------------------------------


@dataclass
class CompiledRule:
    """Pre-resolved rule — no enum comparison or dict lookup in the hot path."""
    __slots__ = (
        "op_fn", "source_keys", "target_name", "reserve_name",
        "max_amount", "condition_trigger", "condition_invert",
        "rule_id", "order", "rule_type_str",
    )
    op_fn: Any
    source_keys: tuple
    target_name: str
    reserve_name: str | None
    max_amount: float | None
    condition_trigger: str | None
    condition_invert: bool
    rule_id: str
    order: int
    rule_type_str: str


# Dispatch tag constants (avoid enum comparison in hot loop)
_OP_INTEREST = 1
_OP_INTEREST_SF = 2
_OP_PRINCIPAL = 3
_OP_WRITEDOWN = 4
_OP_FEE = 5
_OP_RESIDUAL = 6
_OP_TO_RESERVE = 7
_OP_FROM_RESERVE_INT = 8
_OP_FROM_RESERVE_PRIN = 9
_OP_FROM_RESERVE = 10

_RULE_TYPE_TO_TAG = {
    _RT.PAY_INTEREST: _OP_INTEREST,
    _RT.PAY_INTEREST_SHORTFALL: _OP_INTEREST_SF,
    _RT.PAY_PRINCIPAL: _OP_PRINCIPAL,
    _RT.PAY_WRITEDOWN: _OP_WRITEDOWN,
    _RT.PAY_FEE: _OP_FEE,
    _RT.PAY_RESIDUAL: _OP_RESIDUAL,
    _RT.PAY_TO_RESERVE: _OP_TO_RESERVE,
    _RT.PAY_FROM_RESERVE_INTEREST: _OP_FROM_RESERVE_INT,
    _RT.PAY_FROM_RESERVE_PRINCIPAL: _OP_FROM_RESERVE_PRIN,
    _RT.PAY_FROM_RESERVE: _OP_FROM_RESERVE,
}


def _compile_rules(deal: DealDefinition) -> list[tuple]:
    """Pre-compile waterfall rules into a flat dispatch list.

    Each entry is (op_tag, source_keys, target_name, reserve_name,
                   max_amount, condition_trigger, condition_invert,
                   rule_id, order, rule_type_str).
    """
    sorted_rules = sorted(deal.waterfall_rules, key=lambda r: r.order)
    compiled: list[tuple] = []

    for rule in sorted_rules:
        tag = _RULE_TYPE_TO_TAG.get(rule.rule_type, 0)
        src_keys = tuple(rule.from_sources)
        for tgt_name in rule.to_targets:
            compiled.append((
                tag,
                src_keys,
                tgt_name,
                rule.reserve_account,
                rule.max_amount_fixed,
                rule.condition_trigger,
                rule.condition_invert,
                rule.rule_id,
                rule.order,
                rule.rule_type.value,
            ))

    return compiled


# ---------------------------------------------------------------------------
# Trigger evaluation
# ---------------------------------------------------------------------------


def _evaluate_triggers(
    deal: DealDefinition,
    bonds: dict[str, BondWorkspace],
    collateral: dict[str, np.ndarray],
    i: int,
    trigger_states: dict[str, bool],
    orig_collat_bal: float,
    cum_loss_cache: np.ndarray | None = None,
) -> dict[str, bool]:
    for trigger in deal.triggers:
        active = False
        if trigger.metric_type.value == "CUMULATIVE_LOSS":
            if cum_loss_cache is not None:
                metric = cum_loss_cache[i] / orig_collat_bal if orig_collat_bal > 0 else 0.0
            else:
                metric = float(np.sum(collateral["loss"][:i + 1])) / orig_collat_bal if orig_collat_bal > 0 else 0.0

            threshold = trigger.threshold_value or 0.0
            if trigger.threshold_schedule and i < len(trigger.threshold_schedule):
                threshold = trigger.threshold_schedule[i]

            active = metric > threshold

            trig_bond = bonds.get(trigger.name)
            if trig_bond is not None:
                trig_bond.trigger_val[i] = metric
                trig_bond.trigger_tgt[i] = threshold
                trig_bond.trigger_event[i] = active

        trigger_states[trigger.name] = active
    return trigger_states


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------


def _extract_collateral_arrays(run_input: DealRunInput) -> dict[str, np.ndarray]:
    coll = run_input.collateral
    if isinstance(coll, PooledCollateralInput):
        cf = coll.collateral
    elif isinstance(coll, GroupedCollateralInput):
        cf = next(iter(coll.groups.values()))
    elif isinstance(coll, StripCollateralInput):
        cf = coll.principal_strip
    else:
        raise TypeError(f"Unknown collateral input type: {type(coll)}")

    return {
        fname: np.array(getattr(cf, fname), dtype=float)
        for fname in cf.__class__.model_fields
        if fname != "cfdate" and isinstance(getattr(cf, fname), list)
    }


def run_deal(
    deal: DealDefinition,
    run_input: DealRunInput,
    scenario_name: str = "Base Case",
    *,
    collect_trace: bool = True,
) -> ScenarioOutputBundle:
    """Execute a deal waterfall and return the full output bundle for one scenario.

    Args:
        deal:          Immutable deal IR.
        run_input:     Collateral cashflows and overrides.
        scenario_name: Label for this scenario in outputs.
        collect_trace: If False, skip waterfall trace collection (faster for solvers).
    """
    collateral = _extract_collateral_arrays(run_input)
    cf_len = len(collateral["balance"])
    collat_bal_0 = float(collateral["balance"][0])
    orig_collat_bal = run_input.original_collateral_balance or collat_bal_0

    # --- Allocate bond workspaces ---
    bonds: dict[str, BondWorkspace] = {}
    for bond_def in deal.bonds:
        bonds[bond_def.name] = _allocate_bond_workspace(bond_def, cf_len, collat_bal_0)

    if "R" not in bonds:
        bonds["R"] = BondWorkspace(
            name="R", is_bond=False, is_pseudo=True,
            balance=np.zeros(cf_len), principal=np.zeros(cf_len),
            interest=np.zeros(cf_len), opt_interest=np.zeros(cf_len),
            opt_coupons=np.zeros(cf_len), int_shortfall=np.zeros(cf_len),
            coupons=np.zeros(cf_len), cashflow=np.zeros(cf_len),
            writedown=np.zeros(cf_len), trigger_val=np.zeros(cf_len),
            trigger_tgt=np.zeros(cf_len), trigger_event=[""] * cf_len,
            xs_spread=np.zeros(cf_len), xs_spread_cpn=np.zeros(cf_len),
        )

    # --- Pre-compile dispatch table ---
    compiled = _compile_rules(deal)

    # --- Pre-compute cumulative loss for trigger eval ---
    cum_loss_cache = np.cumsum(collateral["loss"]) if deal.triggers else None

    # --- Allocate trace buffer as raw tuples (deferred Pydantic) ---
    trace_buf: list[tuple] | None = [] if collect_trace else None

    # --- Period loop ---
    trigger_states: dict[str, bool] = {}
    cash_avail = np.zeros(cf_len)

    for i in range(1, cf_len):
        update_bonds_pre_ws(bonds, i)

        if deal.triggers:
            _evaluate_triggers(
                deal, bonds, collateral, i, trigger_states, orig_collat_bal, cum_loss_cache,
            )

        cash_avail[i] = collateral["cashflow"][i]

        for (tag, src_keys, tgt_name, reserve_name, max_amt,
             cond_trigger, cond_invert, rule_id, order, rt_str) in compiled:

            if cond_trigger:
                trig_active = trigger_states.get(cond_trigger, False)
                if cond_invert:
                    trig_active = not trig_active
                if not trig_active:
                    continue

            tgt = bonds.get(tgt_name)
            if tgt is None:
                continue

            sources = [cash_avail]
            pmt = 0.0

            if tag == _OP_INTEREST:
                pmt = pay_interest(sources, tgt.interest, tgt.opt_interest, tgt.int_shortfall, i, max_amount=max_amt)
            elif tag == _OP_INTEREST_SF:
                pmt = pay_interest(sources, tgt.interest, tgt.opt_interest, tgt.int_shortfall, i, max_amount=max_amt, shortfall=True)
            elif tag == _OP_PRINCIPAL:
                pmt = pay_principal(sources, tgt.principal, tgt.balance, i, max_amount=max_amt)
            elif tag == _OP_WRITEDOWN:
                pmt = pay_writedown(sources, tgt.writedown, tgt.balance, i, max_amount=max_amt)
            elif tag == _OP_FEE:
                pmt = pay_fee(sources, tgt.interest, i, max_amt if max_amt is not None else 0.0)
            elif tag == _OP_RESIDUAL:
                pmt = pay_residual(sources, tgt.interest, i, max_amt)
            elif tag == _OP_TO_RESERVE:
                pmt = pay_to_reserve(sources, tgt.balance, tgt.principal, i, max_amount=max_amt if max_amt is not None else 0.0)
            elif tag == _OP_FROM_RESERVE_INT:
                if reserve_name and reserve_name in bonds:
                    rsv = bonds[reserve_name]
                    pmt = pay_interest_from_reserve(sources, tgt.interest, tgt.opt_interest, tgt.int_shortfall, rsv.balance, rsv.principal, i, max_amount=max_amt)
            elif tag == _OP_FROM_RESERVE_PRIN:
                if reserve_name and reserve_name in bonds:
                    rsv = bonds[reserve_name]
                    pmt = pay_principal_from_reserve(sources, tgt.principal, tgt.balance, rsv.balance, rsv.principal, i, max_amount=max_amt)
            elif tag == _OP_FROM_RESERVE:
                if reserve_name and reserve_name in bonds:
                    rsv = bonds[reserve_name]
                    pmt = pay_from_reserve(sources, tgt.interest, rsv.balance, rsv.principal, i, max_amt)

            if trace_buf is not None:
                trace_buf.append((
                    scenario_name, i, rule_id, order, rt_str,
                    ",".join(src_keys), tgt_name,
                    max_amt or 0.0, pmt,
                    0.0, 0.0,
                    cond_trigger, trigger_states.get(cond_trigger) if cond_trigger else None,
                ))

        update_bonds_post_ws(bonds, i)

    # --- Finalize bonds ---
    for ws in bonds.values():
        finalize_bond_ws(ws, ws.is_pseudo, ws.is_bond)

    # --- Build output: deferred Pydantic construction ---
    bond_cf_rows: list[BondCashflowRow] = []
    for ws in bonds.values():
        bal = ws.balance
        prin = ws.principal
        opt_int = ws.opt_interest
        intr = ws.interest
        sf = ws.int_shortfall
        wd = ws.writedown
        cf = ws.cashflow
        cpn = ws.coupons
        nm = ws.name
        for p in range(cf_len):
            bond_cf_rows.append(BondCashflowRow(
                scenario_name=scenario_name,
                tranche_id=nm,
                period=p,
                begin_balance=float(bal[p - 1]) if p > 0 else float(bal[0]),
                total_principal=float(prin[p]),
                interest_due=float(opt_int[p]),
                interest_paid=float(intr[p]),
                interest_shortfall=float(sf[p]),
                writedown=float(wd[p]),
                end_balance=float(bal[p]),
                cashflow_total=float(cf[p]),
                coupon_rate=float(cpn[p]),
            ))

    # Convert trace tuples to Pydantic only at end
    trace_rows: list[WaterfallTraceRow] = []
    if trace_buf:
        for t in trace_buf:
            trace_rows.append(WaterfallTraceRow(
                scenario_name=t[0], period=t[1], rule_id=t[2],
                rule_order=t[3], rule_type=t[4],
                from_source=t[5], to_target=t[6],
                amount_requested=t[7], amount_paid=t[8],
                remaining_source=t[9], remaining_obligation=t[10],
                condition_id=t[11], condition_result=t[12],
            ))

    return ScenarioOutputBundle(
        scenario_name=scenario_name,
        bond_cashflows=bond_cf_rows,
        waterfall_trace=trace_rows,
    )
