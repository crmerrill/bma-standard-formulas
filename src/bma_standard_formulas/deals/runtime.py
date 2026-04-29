"""Waterfall runtime engine — executes DealDefinition IR against collateral inputs."""
from dataclasses import dataclass, field
import ast
import operator as _op
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
    pay_recourse_interest,
    pay_recourse_principal,
    pay_residual,
    pay_to_reserve,
    pay_writedown,
    update_bonds_post_ws,
    update_bonds_pre_ws,
)
from .schemas.common import RuleType, TriggerState
from .schemas.input import (
    DealRunInput,
    GroupedCollateralInput,
    PooledCollateralInput,
    StripCollateralInput,
)
from .schemas.ir import DealDefinition
from .schemas.output_bond import BondCashflowRow
from .schemas.output_bundle import ScenarioOutputBundle
from .schemas.output_waterfall import DealAccountRow, TriggerStateRow, WaterfallTraceRow
from .tranche_behaviors import build_tranche_behavior_diagnostics


_RT = RuleType


@dataclass
class BondWorkspace:
    """Mutable workspace arrays for a single bond during execution."""

    name: str
    is_bond: bool
    is_pseudo: bool
    pay_mode: str
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

    # Tranche behavior fields (PAC/TAC schedule-first enforcement and Z accrual).
    tranche_behavior: str = "SEQUENTIAL"
    schedule_cap: np.ndarray | None = None  # length cf_len when PAC/TAC, else None.
    support_tranches: tuple[str, ...] = ()
    supported_by_tranches: tuple[str, ...] = ()
    z_accrual_enabled: bool = False
    z_released: bool = False
    z_release_trigger: str | None = None


@dataclass
class AccountWorkspace:
    """Mutable workspace arrays for account/reserve balances."""

    name: str
    account_type: str
    balance: np.ndarray
    deposit: np.ndarray
    withdrawal: np.ndarray
    required_minimum: np.ndarray
    minimum_basis: str


@dataclass
class CompiledRulePlan:
    """Typed compiled rule plan for one RuleNode."""

    tag: int
    source_keys: tuple[str, ...]
    target_names: tuple[str, ...]
    reserve_name: str | None
    max_amount_fixed: float | None
    max_amount_expr: str | None
    condition_trigger: str | None
    condition_invert: bool
    condition_expr: str | None
    allow_negative_source: bool
    rule_id: str
    order: int
    rule_type_str: str
    payment_style: str
    # `cap_mode` is the canonical schedule-cap interpretation. PLANNED,
    # SCHEDULED, and TARGETED all enforce the bond's `schedule_contract`
    # end-of-period balance target (mathematically identical, names mirror
    # prospectus vocabulary). NONE bypasses the cap (cleanup pattern).
    cap_mode: str = "PLANNED"
    # Retained for legacy code paths and trace output; equivalent to
    # `cap_mode == "NONE"`.
    ignore_schedule_cap: bool = False
    # Per-target weights for SPLIT_CASH rules; one entry per target_name,
    # summing to <= 1.0. None for non-SPLIT_CASH rules.
    target_weights: tuple[float, ...] | None = None


@dataclass
class ExecutionContext:
    """Mutable state for one scenario run."""

    scenario_name: str
    collateral: dict[str, np.ndarray]
    bonds: dict[str, BondWorkspace]
    accounts: dict[str, AccountWorkspace]
    fee_defs_by_name: dict[str, Any]
    compiled_rules: list[CompiledRulePlan]
    trigger_states: dict[str, bool] = field(default_factory=dict)
    calculation_values: dict[str, float] = field(default_factory=dict)
    virtual_sources: dict[str, np.ndarray] = field(default_factory=dict)
    cash_avail: np.ndarray | None = None
    # Independent pool-interest and pool-principal streams, populated each
    # period from `collateral["interest"]` and `collateral["principal"]`.
    # Rules that reference source key `INT_CASH` or `PRIN_CASH` draw from
    # these instead of the combined `CASH` stream, so PAY_INTEREST and
    # PAY_PRINCIPAL rules cannot accidentally cross-fund each other. Deals
    # are responsible for picking one convention (combined `CASH` *or* split
    # `INT_CASH` + `PRIN_CASH`) per scenario; mixing the two double-counts
    # cash because the streams are independent decrementable arrays.
    interest_avail: np.ndarray | None = None
    principal_avail: np.ndarray | None = None
    # Per-group collateral and cash arrays for multi-pool deals. When the
    # deal's `collateral_groups` is empty (single-pool deal), these are
    # left empty and rules use the bare `cash_avail` / `interest_avail`
    # / `principal_avail` arrays. When the deal declares multiple
    # groups, each group_id maps to its own decrementable arrays so
    # `GROUP_<id>_CASH` / `GROUP_<id>_INT_CASH` / `GROUP_<id>_PRIN_CASH`
    # source tokens route to the right pool. The single-pool primary
    # arrays are populated as the *aggregate* across groups (sum of all
    # group cashflows) so trigger metrics and account-level computations
    # see the deal-wide totals; rule routing uses the per-group arrays.
    collateral_by_group: dict[str, dict[str, np.ndarray]] = field(default_factory=dict)
    cash_avail_by_group: dict[str, np.ndarray] = field(default_factory=dict)
    interest_avail_by_group: dict[str, np.ndarray] = field(default_factory=dict)
    principal_avail_by_group: dict[str, np.ndarray] = field(default_factory=dict)
    trace_buf: list[tuple] | None = None
    trigger_rows: list[TriggerStateRow] = field(default_factory=list)
    # Per-period dictionary of `cash_at_<rule_id>` snapshots so a later rule
    # can anchor its `max_amount_expr` to the cash level at an earlier rule
    # boundary (used to model face-weighted percentage splits like the FNR
    # 2006-018 95.65 / 4.35 support cash distribution).
    rule_cash_snapshots: dict[str, float] = field(default_factory=dict)


def _build_schedule_cap(bond_def: Any, cf_len: int) -> np.ndarray | None:
    """Build a per-period planned-balance vector from schedule_contract entries.

    Each `schedule_contract` entry is `{period, target_balance}` — the
    end-of-period planned balance for the bond at that distribution date.
    Sparse entries are forward-filled (a missing month uses the most recent
    prior published balance, matching the convention in
    `expand_to_monthly_balance_vector` for published planned-balance
    schedules that carry forward through "lockout" periods).

    Backward compatibility: legacy `target_principal` entries are converted
    into a balance vector by treating successive principal targets as
    decrements from the bond's initial balance. This preserves existing IR
    payloads that predate the to-Planned-Balance semantics fix.

    Returns None when the bond does not carry a schedule_contract.
    """
    contract = getattr(bond_def, "schedule_contract", None) or []
    if not contract:
        return None

    # Determine bond face for legacy translation / forward-fill anchoring.
    bond_face: float
    if bond_def.size_dollars is not None and bond_def.size_dollars > 0:
        bond_face = float(bond_def.size_dollars)
    elif bond_def.size_pct is not None and bond_def.size_pct > 0:
        bond_face = float(bond_def.size_pct)  # caller will scale; not used numerically here.
    else:
        bond_face = 0.0

    target_balance = np.full(cf_len, np.nan)
    legacy_principal = np.zeros(cf_len)
    has_target_balance = False
    has_target_principal = False
    for entry in contract:
        if not isinstance(entry, dict):
            continue
        try:
            period = int(entry.get("period", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not (0 <= period < cf_len):
            continue
        if entry.get("target_balance") is not None:
            try:
                target_balance[period] = float(entry["target_balance"])
                has_target_balance = True
            except (TypeError, ValueError):
                pass
        if entry.get("target_principal") is not None:
            try:
                legacy_principal[period] = float(entry["target_principal"])
                has_target_principal = True
            except (TypeError, ValueError):
                pass

    if has_target_balance:
        # Forward-fill any missing balance entries from the most recent prior.
        last = float(bond_face)
        cap = np.empty(cf_len, dtype=float)
        for i in range(cf_len):
            if not np.isnan(target_balance[i]):
                last = float(target_balance[i])
            cap[i] = last
        return cap

    if has_target_principal:
        # Translate per-period principal targets into running planned balance.
        cap = np.empty(cf_len, dtype=float)
        running = float(bond_face)
        for i in range(cf_len):
            running = max(0.0, running - float(legacy_principal[i]))
            cap[i] = running
        return cap

    return None


def _allocate_bond_workspace(
    bond_def: Any,
    cf_len: int,
    collateral_balance_0: float,
) -> BondWorkspace:
    # Authoritative sizing is dollar face. Percent-of-collateral is derived UX context.
    if bond_def.size_dollars is not None and bond_def.size_dollars > 0:
        initial_balance = bond_def.size_dollars
    elif bond_def.size_pct is not None and bond_def.size_pct > 0:
        initial_balance = collateral_balance_0 * bond_def.size_pct / 100.0
    else:
        initial_balance = 0.0

    balance = np.zeros(cf_len)
    balance[0] = initial_balance

    # LDCMA-like behavior: pseudo non-bonds carry forward from initialized balance.
    # Most pseudo fee nodes start at 0, while reserve-like pseudo nodes can start
    # with an explicit configured balance.
    if bond_def.is_pseudo and not bond_def.is_bond:
        balance[:] = 0.0
        balance[0] = initial_balance
        tranche_type = getattr(getattr(bond_def, "tranche_type", None), "value", None)
        if tranche_type == "RESIDUAL" and balance[0] <= 0.0:
            # LDCMA initializes residual pseudo bond with collateral start balance.
            balance[0] = collateral_balance_0

    opt_coupons = np.zeros(cf_len)
    if bond_def.is_bond and not bond_def.is_pseudo:
        if bond_def.coupon_type.value == "FIXED" and bond_def.coupon is not None:
            opt_coupons[:] = bond_def.coupon

    behavior = getattr(getattr(bond_def, "tranche_behavior", None), "value", "SEQUENTIAL")
    schedule_cap = _build_schedule_cap(bond_def, cf_len) if behavior in ("PAC", "TAC") else None

    return BondWorkspace(
        name=bond_def.name,
        is_bond=bond_def.is_bond and not bond_def.is_pseudo,
        is_pseudo=bond_def.is_pseudo,
        pay_mode=getattr(getattr(bond_def, "pay_mode", None), "value", "CASH_PAY"),
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
        tranche_behavior=behavior,
        schedule_cap=schedule_cap,
        support_tranches=tuple(getattr(bond_def, "support_tranches", []) or []),
        supported_by_tranches=tuple(getattr(bond_def, "supported_by_tranches", []) or []),
        z_accrual_enabled=bool(getattr(bond_def, "z_accrual_enabled", False)),
        z_released=False,
        z_release_trigger=getattr(bond_def, "z_release_trigger", None),
    )


def _allocate_account_workspace(account_def: Any, cf_len: int, collateral_balance_0: float) -> AccountWorkspace:
    starting_amount = float(account_def.starting_amount or 0.0)
    if account_def.starting_pct is not None:
        starting_amount = collateral_balance_0 * float(account_def.starting_pct) / 100.0
    minimum = float(account_def.minimum_amount or 0.0)
    if account_def.minimum_pct is not None:
        minimum = max(minimum, collateral_balance_0 * float(account_def.minimum_pct) / 100.0)

    balance = np.zeros(cf_len)
    balance[0] = starting_amount
    required_minimum = np.zeros(cf_len)
    required_minimum[:] = minimum
    return AccountWorkspace(
        name=account_def.name,
        account_type=account_def.account_type.value,
        balance=balance,
        deposit=np.zeros(cf_len),
        withdrawal=np.zeros(cf_len),
        required_minimum=required_minimum,
        minimum_basis=account_def.minimum_basis.value,
    )


# Dispatch tags
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
_OP_RECOURSE_INT = 11
_OP_RECOURSE_PRIN = 12
_OP_SPLIT_CASH = 13

_RULE_TYPE_TO_TAG: dict[RuleType, int] = {
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
    _RT.PAY_RECOURSE_INTEREST: _OP_RECOURSE_INT,
    _RT.PAY_RECOURSE_PRINCIPAL: _OP_RECOURSE_PRIN,
    _RT.SPLIT_CASH: _OP_SPLIT_CASH,
}


def _scope_sources_to_group(keys: tuple[str, ...], group_id: str | None) -> tuple[str, ...]:
    """Rewrite bare cashflow tokens in a rule's source/target list to be
    scoped to the rule's collateral group.

    When a rule declares ``group_id="GROUP_1"``, the runtime treats its
    bare ``CASH`` / ``INT_CASH`` / ``PRIN_CASH`` / ``COLLATERAL`` /
    ``LOSS`` tokens as shorthand for ``GROUP_GROUP_1_CASH`` etc. This
    keeps deal definitions readable: instead of typing the prefixed
    form everywhere, the IR author tags the rule once with its group
    and the bare tokens follow.

    No-op when ``group_id`` is None or the key is already prefixed.
    """
    if not group_id:
        return keys
    SCOPED = {"CASH", "INT_CASH", "PRIN_CASH", "COLLATERAL", "LOSS"}
    out: list[str] = []
    for key in keys:
        if key in SCOPED:
            out.append(f"GROUP_{group_id}_{key}")
        else:
            out.append(key)
    return tuple(out)


def _compile_rules(deal: DealDefinition) -> list[CompiledRulePlan]:
    sorted_rules = sorted(deal.waterfall_rules, key=lambda r: r.order)
    compiled: list[CompiledRulePlan] = []
    for rule in sorted_rules:
        # Resolve cap_mode: explicit IR field wins; otherwise honor legacy
        # ignore_schedule_cap=True; otherwise default to PLANNED (the standard
        # PAC interpretation when a schedule is present on the target bond).
        explicit_cap_mode = getattr(rule, "cap_mode", None)
        legacy_ignore = bool(getattr(rule, "ignore_schedule_cap", False))
        if explicit_cap_mode is not None:
            cap_mode_str = explicit_cap_mode.value if hasattr(explicit_cap_mode, "value") else str(explicit_cap_mode)
        elif legacy_ignore:
            cap_mode_str = "NONE"
        else:
            cap_mode_str = "PLANNED"
        ignore_flag = (cap_mode_str == "NONE")
        weights = (
            tuple(float(w) for w in rule.target_weights)
            if rule.target_weights is not None
            else None
        )
        compiled.append(
            CompiledRulePlan(
                tag=_RULE_TYPE_TO_TAG.get(rule.rule_type, 0),
                source_keys=_scope_sources_to_group(
                    tuple(rule.from_sources), rule.group_id,
                ),
                target_names=_scope_sources_to_group(
                    tuple(rule.to_targets), rule.group_id,
                ),
                reserve_name=rule.reserve_account,
                max_amount_fixed=rule.max_amount_fixed,
                max_amount_expr=rule.max_amount_expr,
                condition_trigger=rule.condition_trigger,
                condition_invert=rule.condition_invert,
                condition_expr=rule.condition_expr,
                allow_negative_source=rule.allow_negative_source,
                rule_id=rule.rule_id,
                order=rule.order,
                rule_type_str=rule.rule_type.value,
                payment_style=rule.payment_style.value,
                cap_mode=cap_mode_str,
                ignore_schedule_cap=ignore_flag,
                target_weights=weights,
            )
        )
    return compiled


def _cashflow_arrays(cf: Any) -> dict[str, np.ndarray]:
    """Convert a CollateralCashflows model into a dict of numpy arrays."""
    return {
        fname: np.array(getattr(cf, fname), dtype=float)
        for fname in cf.__class__.model_fields
        if fname != "cfdate" and isinstance(getattr(cf, fname), list)
    }


def _extract_collateral_arrays(
    run_input: DealRunInput,
) -> tuple[dict[str, np.ndarray], dict[str, dict[str, np.ndarray]]]:
    """Extract collateral arrays as (aggregate, per_group).

    For single-pool inputs the aggregate is the only pool and per_group
    is empty. For grouped inputs the aggregate is the period-wise sum
    across all groups (used by triggers and pool-wide metrics) and
    per_group maps each group_id to its own set of arrays (used by
    rule routing for ``GROUP_<id>_CASH`` / ``INT_CASH`` / ``PRIN_CASH``
    source tokens).
    """
    coll = run_input.collateral
    if isinstance(coll, PooledCollateralInput):
        return _cashflow_arrays(coll.collateral), {}
    if isinstance(coll, GroupedCollateralInput):
        per_group: dict[str, dict[str, np.ndarray]] = {
            gid: _cashflow_arrays(cf) for gid, cf in coll.groups.items()
        }
        # Aggregate = period-wise sum across groups for the fields that
        # are summable. Counts/rates (cpr, cdr, sev, dq, surv_fac,
        # coupons, sched_balance, discount_factor) don't aggregate
        # cleanly, so we copy them from the first group; downstream
        # uses of those fields are only meaningful per-group anyway.
        first_gid = next(iter(per_group))
        first = per_group[first_gid]
        n = len(first["balance"])
        summable = {
            "balance", "principal", "interest", "cashflow", "loss",
            "prepbal", "defbal", "recovery", "principal_sched",
            "principal_unsched",
        }
        agg: dict[str, np.ndarray] = {}
        for fname, arr in first.items():
            if fname in summable:
                acc = np.zeros(n)
                for g in per_group.values():
                    acc = acc + g[fname][:n] if len(g[fname]) >= n else acc
                # Rebuild with sums across all groups, period-aligned.
                acc = np.zeros(n)
                for g in per_group.values():
                    aa = g[fname]
                    if len(aa) < n:
                        # Pad short groups with zeros so summation is well-defined.
                        padded = np.zeros(n)
                        padded[: len(aa)] = aa
                        acc = acc + padded
                    else:
                        acc = acc + aa[:n]
                agg[fname] = acc
            else:
                agg[fname] = np.array(arr, dtype=float)
        return agg, per_group
    if isinstance(coll, StripCollateralInput):
        cf = coll.principal_strip
        return _cashflow_arrays(cf), {}
    raise TypeError(f"Unknown collateral input type: {type(coll)}")


_SAFE_BIN_OPS = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.Pow: _op.pow,
    ast.Mod: _op.mod,
}
_SAFE_UNARY_OPS = {
    ast.UAdd: _op.pos,
    ast.USub: _op.neg,
}
_SAFE_FUNCS = {
    "min": min,
    "max": max,
    "abs": abs,
}


def _safe_eval_expr(expr: str, values: dict[str, float]) -> float:
    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError("Unsupported constant")
        if isinstance(node, ast.Name):
            return float(values.get(node.id, 0.0))
        if isinstance(node, ast.BinOp):
            fn = _SAFE_BIN_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("Unsupported binary operator")
            return float(fn(_eval(node.left), _eval(node.right)))
        if isinstance(node, ast.UnaryOp):
            fn = _SAFE_UNARY_OPS.get(type(node.op))
            if fn is None:
                raise ValueError("Unsupported unary operator")
            return float(fn(_eval(node.operand)))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            fn = _SAFE_FUNCS.get(node.func.id)
            if fn is None:
                raise ValueError("Unsupported function")
            args = [_eval(a) for a in node.args]
            return float(fn(*args))
        raise ValueError("Unsupported expression node")

    return float(_eval(ast.parse(expr, mode="eval")))


def _build_expr_context(
    deal: DealDefinition,
    run_input: DealRunInput,
    collateral: dict[str, np.ndarray],
    bonds: dict[str, BondWorkspace],
    accounts: dict[str, AccountWorkspace],
    trigger_states: dict[str, bool],
    calculation_values: dict[str, float],
    virtual_sources: dict[str, np.ndarray],
    cash_avail: np.ndarray | None,
    i: int,
    orig_collat_bal: float,
) -> dict[str, float]:
    bal = float(collateral["balance"][i])
    bal_prev = float(collateral["balance"][i - 1]) if i > 0 else bal
    ctx: dict[str, float] = {
        "period": float(i),
        "collateral_balance": bal,
        "collateral_balance_prev": bal_prev,
        "collateral_cashflow": float(collateral["cashflow"][i]),
        "collateral_interest": float(collateral["interest"][i]),
        "collateral_principal": float(collateral["principal"][i]),
        "collateral_loss": float(collateral["loss"][i]),
        "cash_available": float(cash_avail[i]) if cash_avail is not None else 0.0,
        "loan_count": float(run_input.loan_count or 0),
        "orig_collateral_balance": float(orig_collat_bal),
        "surv_fac_prev": float(collateral["surv_fac"][i - 1]) if i > 0 and "surv_fac" in collateral else 1.0,
    }
    for key, value in (deal.deal_knobs or {}).items():
        if isinstance(value, (int, float)) and key.isidentifier():
            ctx[key] = float(value)
    for name, ws in bonds.items():
        if name.isidentifier():
            ctx[f"{name}_balance"] = float(ws.balance[i])
            ctx[f"{name}_principal"] = float(ws.principal[i])
            ctx[f"{name}_interest"] = float(ws.interest[i])
            ctx[f"{name}_shortfall"] = float(ws.int_shortfall[i])
    for name, ws in accounts.items():
        if name.isidentifier():
            ctx[f"{name}_balance"] = float(ws.balance[i])
            ctx[f"{name}_deposit"] = float(ws.deposit[i])
            ctx[f"{name}_withdrawal"] = float(ws.withdrawal[i])
    for trig_name, active in trigger_states.items():
        if trig_name.isidentifier():
            ctx[f"{trig_name}_active"] = 1.0 if active else 0.0
    for calc_name, value in calculation_values.items():
        if calc_name.isidentifier():
            ctx[calc_name] = float(value)
    for src_name, arr in virtual_sources.items():
        if src_name.isidentifier():
            ctx[f"{src_name}_available"] = float(arr[i])
    return ctx


def _evaluate_calculations(deal: DealDefinition, base_ctx: dict[str, float]) -> dict[str, float]:
    if not deal.calculations:
        return {}
    values = dict(base_ctx)
    out: dict[str, float] = {}
    pending = {c.name: c.expression for c in deal.calculations}
    for _ in range(len(pending) + 2):
        progressed = False
        for name in list(pending.keys()):
            expr = pending[name]
            try:
                val = _safe_eval_expr(expr, values)
            except Exception:
                continue
            out[name] = val
            values[name] = val
            pending.pop(name, None)
            progressed = True
        if not pending or not progressed:
            break
    for name in pending:
        out[name] = 0.0
    return out


def _resolve_source_arrays(ctx: ExecutionContext, source_keys: tuple[str, ...]) -> list[np.ndarray]:
    arrays: list[np.ndarray] = []
    for key in source_keys:
        # Per-group cash streams: GROUP_<id>_(CASH|INT_CASH|PRIN_CASH|
        # COLLATERAL|LOSS). Multi-pool deals (e.g. Fannie Mae REMIC
        # trusts with Group 1 + Group 2 separately-collateralized
        # bonds) route every collateral-touching rule through these
        # so cashflows stay segregated by group. Match longest group
        # id first to avoid ambiguity if group ids share prefixes.
        if key.startswith("GROUP_") and ctx.collateral_by_group:
            matched = False
            sorted_gids = sorted(ctx.collateral_by_group.keys(), key=len, reverse=True)
            for gid in sorted_gids:
                prefix = f"GROUP_{gid}_"
                if key.startswith(prefix):
                    suffix = key[len(prefix):]
                    if suffix == "INT_CASH":
                        arrays.append(ctx.interest_avail_by_group[gid])
                    elif suffix == "PRIN_CASH":
                        arrays.append(ctx.principal_avail_by_group[gid])
                    elif suffix in ("CASH", "COLLATERAL"):
                        arrays.append(ctx.cash_avail_by_group[gid])
                    elif suffix == "LOSS":
                        arrays.append(ctx.collateral_by_group[gid]["loss"])
                    matched = True
                    break
            if matched:
                continue
        # Split-stream sources: INT_CASH = pool interest, PRIN_CASH = pool
        # principal. Independent arrays, so rules that draw from these do not
        # interfere with the combined `CASH` stream (which still carries
        # principal + interest combined). A deal should pick one convention.
        if key == "INT_CASH" and ctx.interest_avail is not None:
            arrays.append(ctx.interest_avail)
            continue
        if key == "PRIN_CASH" and ctx.principal_avail is not None:
            arrays.append(ctx.principal_avail)
            continue
        if key in ("CASH", "COLLATERAL") and ctx.cash_avail is not None:
            arrays.append(ctx.cash_avail)
            continue
        if key == "LOSS" and "loss" in ctx.collateral:
            arrays.append(ctx.collateral["loss"])
            continue
        acct = ctx.accounts.get(key)
        if acct is not None:
            arrays.append(acct.balance)
            continue
        bond = ctx.bonds.get(key)
        if bond is not None:
            arrays.append(bond.balance)
            continue
        virt = ctx.virtual_sources.get(key)
        if virt is not None:
            arrays.append(virt)
    if not arrays and ctx.cash_avail is not None:
        arrays.append(ctx.cash_avail)
    return arrays


def _update_virtual_sources(
    deal: DealDefinition,
    ctx: ExecutionContext,
    run_input: DealRunInput,
    i: int,
    orig_collat_bal: float,
) -> None:
    formulas = deal.deal_knobs.get("source_formulas")
    if not isinstance(formulas, dict):
        return
    expr_ctx = _build_expr_context(
        deal,
        run_input,
        ctx.collateral,
        ctx.bonds,
        ctx.accounts,
        ctx.trigger_states,
        ctx.calculation_values,
        ctx.virtual_sources,
        ctx.cash_avail,
        i,
        orig_collat_bal,
    )
    for src_name, expr in formulas.items():
        if not isinstance(src_name, str) or not isinstance(expr, str):
            continue
        if src_name not in ctx.virtual_sources:
            ctx.virtual_sources[src_name] = np.zeros_like(ctx.cash_avail if ctx.cash_avail is not None else np.zeros(1))
        try:
            value = max(0.0, float(_safe_eval_expr(expr, expr_ctx)))
        except Exception:
            value = 0.0
        ctx.virtual_sources[src_name][i] = value


def _apply_balance_trackers(
    deal: DealDefinition,
    ctx: ExecutionContext,
    run_input: DealRunInput,
    i: int,
    orig_collat_bal: float,
) -> None:
    trackers = deal.deal_knobs.get("balance_trackers")
    if not isinstance(trackers, dict):
        return
    expr_ctx = _build_expr_context(
        deal,
        run_input,
        ctx.collateral,
        ctx.bonds,
        ctx.accounts,
        ctx.trigger_states,
        ctx.calculation_values,
        ctx.virtual_sources,
        ctx.cash_avail,
        i,
        orig_collat_bal,
    )
    for target_name, expr in trackers.items():
        if not isinstance(target_name, str) or not isinstance(expr, str):
            continue
        tgt = ctx.bonds.get(target_name)
        if tgt is None:
            acct = ctx.accounts.get(target_name)
            if acct is None:
                continue
            try:
                acct.balance[i] = float(_safe_eval_expr(expr, expr_ctx))
            except Exception:
                pass
            continue
        try:
            tgt.balance[i] = float(_safe_eval_expr(expr, expr_ctx))
        except Exception:
            pass


def _resolve_fee_due_amount(
    fee_def: Any,
    run_input: DealRunInput,
    collateral_balance_start: float,
    i: int,
    expr_context: dict[str, float] | None = None,
) -> float:
    """Compute scheduled fee amount for current period from fee definition."""
    if fee_def is None:
        return 0.0
    basis = getattr(fee_def, "basis_type", None)
    basis_val = basis.value if hasattr(basis, "value") else str(basis)
    amount = float(getattr(fee_def, "amount", 0.0) or 0.0)
    if getattr(fee_def, "amount_expr", None):
        amount = _safe_eval_expr(str(fee_def.amount_expr), expr_context or {})
    minimum = float(getattr(fee_def, "minimum", 0.0) or 0.0)
    frequency = getattr(fee_def, "frequency", None)
    freq_val = frequency.value if hasattr(frequency, "value") else str(frequency or "MONTHLY")
    periods_per_year = 12
    if freq_val == "QUARTERLY":
        periods_per_year = 4
        if (i % 3) != 0:
            return 0.0
    elif freq_val == "ANNUAL":
        periods_per_year = 1
        if (i % 12) != 0:
            return 0.0

    if i <= 0:
        return 0.0

    due = 0.0
    if basis_val == "FIXED_DOLLAR":
        due = amount / float(periods_per_year)
    elif basis_val == "PER_LOAN":
        due = (amount * float(run_input.loan_count or 0.0)) / float(periods_per_year)
    elif basis_val == "COLLATERAL_BALANCE":
        annual_rate_pct = float(getattr(fee_def, "rate", 0.0) or 0.0)
        if getattr(fee_def, "rate_expr", None):
            annual_rate_pct = _safe_eval_expr(str(fee_def.rate_expr), expr_context or {})
        due = collateral_balance_start * (annual_rate_pct / 100.0) / float(periods_per_year)

    return max(due, minimum)


def _resolve_rule_max_amount(rule: CompiledRulePlan, expr_ctx: dict[str, float], calc_values: dict[str, float]) -> float | None:
    if rule.max_amount_expr:
        full_ctx = dict(expr_ctx)
        full_ctx.update(calc_values)
        return float(_safe_eval_expr(rule.max_amount_expr, full_ctx))
    return rule.max_amount_fixed


def _schedule_remaining(ws: BondWorkspace, period: int) -> float | None:
    """Return remaining principal capacity for a PAC/TAC bond at this period.

    Schedule-first contract under "to Planned Balance" semantics: the bond
    must end the period at the published planned balance for that distribution
    date. The published prospectus language is "to Aggregate Group X to its
    Planned Balance for that Distribution Date" -- the cap is a target
    end-of-period balance, NOT a per-period principal amount.

    `ws.schedule_cap[period]` stores the planned end-of-period balance for
    this bond. The remaining capacity to absorb principal this period equals
    the bond's current balance minus the planned end balance, which lets the
    PAC catch up via additional payments when it has fallen behind in earlier
    periods. Returns 0 once balance is at or below planned.

    Returns None for non-scheduled bonds (no cap applied).
    """
    if ws.schedule_cap is None:
        return None
    planned_balance = float(ws.schedule_cap[period])
    current_balance = float(ws.balance[period])
    return max(0.0, current_balance - planned_balance)


def _effective_principal_cap(ws: BondWorkspace, period: int, rule_max: float | None) -> float | None:
    """Combine balance, schedule, and rule-level caps into an effective max.

    Returns None when no caps apply (i.e. balance-limited only and no rule cap),
    so the existing `pay_principal` semantics keep working unchanged for
    SEQUENTIAL bonds.
    """
    sched = _schedule_remaining(ws, period)
    if sched is None and rule_max is None:
        return None
    candidates: list[float] = []
    if rule_max is not None:
        candidates.append(float(rule_max))
    if sched is not None:
        candidates.append(sched)
    return min(candidates) if candidates else None


def _apply_z_accrual(ctx: ExecutionContext, period: int) -> None:
    """Pre-waterfall Z-bond accrual: PIK interest into balance, paid as support principal.

    Industry-standard Z mechanic: while supports are outstanding, Z does not
    receive cash interest; instead its accrued coupon is capitalized into Z
    balance and an equivalent amount is paid as principal to the support
    stack. Once supports are exhausted, Z transitions to cash-pay (released).

    Order of operations per period:
      1. **Pre-flight release**: if all `supported_by_tranches` are already at
         zero balance entering the period, mark Z as released and skip accrual.
         This ensures Z receives cash interest/principal via the regular
         waterfall in the same period the support was exhausted.
      2. **Apply accrual**: capitalize `opt_interest` into Z balance.
      3. **Pay support principal**: walk supports in declared order, paying
         principal up to each support's balance until accrual is exhausted.
      4. **Zero Z interest**: clear `opt_interest` and `int_shortfall` so the
         regular waterfall does not also pay Z in cash.
      5. **Post-accrual release**: if supports were just paid down to zero,
         mark Z as released for next period.
    """
    for ws in ctx.bonds.values():
        if ws.tranche_behavior != "Z":
            continue
        if not ws.z_accrual_enabled or ws.pay_mode != "PIK":
            continue
        if ws.z_released:
            continue

        # Pre-flight release: supports already exhausted -> Z is released this period.
        if ws.supported_by_tranches:
            all_supports_zero = all(
                (ctx.bonds.get(name) is None) or (float(ctx.bonds[name].balance[period]) <= 1e-9)
                for name in ws.supported_by_tranches
            )
            if all_supports_zero:
                ws.z_released = True
                continue

        accrual = float(ws.opt_interest[period])
        if accrual <= 0.0:
            continue

        # Apply accrual to Z balance and pay support principal subject to each
        # support's schedule cap (industry standard: Z accrual flows to support
        # planned balance, not outstanding balance). Excess accrual capitalizes
        # into Z (already added to Z balance above).
        ws.balance[period] += accrual
        remaining = accrual
        accrual_paid_to_supports = 0.0
        for support_name in ws.supported_by_tranches:
            if remaining <= 0.0:
                break
            support = ctx.bonds.get(support_name)
            if support is None or support.balance[period] <= 0.0:
                continue
            cap = float(support.balance[period])
            sched_remaining = _schedule_remaining(support, period)
            if sched_remaining is not None:
                cap = min(cap, sched_remaining)
            pmt = min(remaining, cap)
            if pmt <= 0.0:
                continue
            support.principal[period] += pmt
            support.balance[period] -= pmt
            remaining -= pmt
            accrual_paid_to_supports += pmt

        # Z accrual is pool interest re-routed to support principal. Decrement
        # the explicit `INT_CASH` stream so a deal that runs interest rules
        # against `INT_CASH` does not double-fund the accrual amount. The
        # combined `CASH` stream is left alone because deals using it have
        # opted into combined-stream semantics by their rule definitions.
        if accrual_paid_to_supports > 0.0 and ctx.interest_avail is not None:
            ctx.interest_avail[period] = max(
                0.0,
                float(ctx.interest_avail[period]) - accrual_paid_to_supports,
            )

        # Z's interest does not pay in cash this period; clear after accrual posted.
        ws.opt_interest[period] = 0.0
        ws.int_shortfall[period] = 0.0

        # Post-accrual release check: supports just paid down to zero?
        post_supports_zero = bool(ws.supported_by_tranches) and all(
            (ctx.bonds.get(name) is None) or (float(ctx.bonds[name].balance[period]) <= 1e-9)
            for name in ws.supported_by_tranches
        )
        if post_supports_zero:
            ws.z_released = True


def _evaluate_triggers(
    deal: DealDefinition,
    ctx: ExecutionContext,
    i: int,
    orig_collat_bal: float,
    cum_loss_cache: np.ndarray | None = None,
) -> dict[str, bool]:
    for trigger in deal.triggers:
        metric = 0.0
        if trigger.calculation_ref:
            metric = float(ctx.calculation_values.get(trigger.calculation_ref, 0.0))
        elif trigger.metric_type.value == "CUMULATIVE_LOSS":
            if cum_loss_cache is not None:
                metric = cum_loss_cache[i] / orig_collat_bal if orig_collat_bal > 0 else 0.0
            else:
                metric = float(np.sum(ctx.collateral["loss"][: i + 1])) / orig_collat_bal if orig_collat_bal > 0 else 0.0

        threshold = trigger.threshold_value or 0.0
        if trigger.threshold_schedule and i < len(trigger.threshold_schedule):
            threshold = trigger.threshold_schedule[i]
        if trigger.comparison_ref:
            threshold = float(ctx.calculation_values.get(trigger.comparison_ref, threshold))
        active = metric > threshold

        trig_bond = ctx.bonds.get(trigger.name)
        if trig_bond is not None:
            trig_bond.trigger_val[i] = metric
            trig_bond.trigger_tgt[i] = threshold
            trig_bond.trigger_event[i] = active

        ctx.trigger_rows.append(
            TriggerStateRow(
                scenario_name=ctx.scenario_name,
                trigger_id=trigger.name,
                period=i,
                metric_value=metric,
                threshold_value=threshold,
                state=TriggerState.FAIL if active else TriggerState.PASS,
            )
        )
        ctx.trigger_states[trigger.name] = active
    return ctx.trigger_states


def run_deal(
    deal: DealDefinition,
    run_input: DealRunInput,
    scenario_name: str = "Base Case",
    *,
    collect_trace: bool = True,
) -> ScenarioOutputBundle:
    """Execute a deal waterfall and return the full output bundle for one scenario."""
    collateral, collateral_by_group = _extract_collateral_arrays(run_input)
    cf_len = len(collateral["balance"])
    collat_bal_0 = float(collateral["balance"][0])
    declared_groups = [g.group_id for g in deal.collateral_groups]
    if declared_groups:
        # Multi-pool deal: each declared group must appear in the
        # GroupedCollateralInput.groups dict so per-group routing can
        # populate its arrays.
        missing = [gid for gid in declared_groups if gid not in collateral_by_group]
        if missing:
            raise ValueError(
                f"DealDefinition declares collateral_groups {declared_groups!r} "
                f"but DealRunInput.collateral is missing groups: {missing!r}. "
                f"Provide a GroupedCollateralInput with one entry per declared "
                f"group_id."
            )
    orig_override = deal.deal_knobs.get("orig_collat_bal_override")
    orig_collat_bal = float(orig_override) if isinstance(orig_override, (int, float)) else float(run_input.original_collateral_balance or collat_bal_0)

    bonds: dict[str, BondWorkspace] = {
        bond_def.name: _allocate_bond_workspace(bond_def, cf_len, collat_bal_0) for bond_def in deal.bonds
    }
    if "R" not in bonds:
        bonds["R"] = BondWorkspace(
            name="R",
            is_bond=False,
            is_pseudo=True,
            pay_mode="CASH_PAY",
            balance=np.zeros(cf_len),
            principal=np.zeros(cf_len),
            interest=np.zeros(cf_len),
            opt_interest=np.zeros(cf_len),
            opt_coupons=np.zeros(cf_len),
            int_shortfall=np.zeros(cf_len),
            coupons=np.zeros(cf_len),
            cashflow=np.zeros(cf_len),
            writedown=np.zeros(cf_len),
            trigger_val=np.zeros(cf_len),
            trigger_tgt=np.zeros(cf_len),
            trigger_event=[""] * cf_len,
            xs_spread=np.zeros(cf_len),
            xs_spread_cpn=np.zeros(cf_len),
        )

    accounts: dict[str, AccountWorkspace] = {
        account_def.name: _allocate_account_workspace(account_def, cf_len, collat_bal_0) for account_def in deal.accounts
    }
    compiled = _compile_rules(deal)
    fee_defs_by_name = {fee.name: fee for fee in deal.fees}
    cum_loss_cache = np.cumsum(collateral["loss"]) if deal.triggers else None
    trace_buf: list[tuple] | None = [] if collect_trace else None
    cash_avail = np.zeros(cf_len)
    # First-class split-stream sources: always populated so deal definitions
    # can choose between the combined `CASH` stream (legacy) or the explicit
    # `INT_CASH` + `PRIN_CASH` streams. The streams are independent
    # decrementable arrays; deals should pick one convention per rule chain
    # (mixing CASH and INT/PRIN double-counts cash).
    interest_avail = np.zeros(cf_len)
    principal_avail = np.zeros(cf_len)
    # Multi-pool deals: allocate parallel per-group cash arrays. Source
    # tokens like ``GROUP_<id>_INT_CASH`` route to these so a Group-1
    # interest waterfall draws only from Group 1's pool. The single-pool
    # ``cash_avail``/``interest_avail``/``principal_avail`` arrays still
    # carry the deal-wide aggregate so triggers and pool-level metrics
    # see totals. Single-pool deals leave these dicts empty.
    cash_avail_by_group: dict[str, np.ndarray] = {}
    interest_avail_by_group: dict[str, np.ndarray] = {}
    principal_avail_by_group: dict[str, np.ndarray] = {}
    for gid in declared_groups:
        cash_avail_by_group[gid] = np.zeros(cf_len)
        interest_avail_by_group[gid] = np.zeros(cf_len)
        principal_avail_by_group[gid] = np.zeros(cf_len)
    ctx = ExecutionContext(
        scenario_name=scenario_name,
        collateral=collateral,
        bonds=bonds,
        accounts=accounts,
        fee_defs_by_name=fee_defs_by_name,
        compiled_rules=compiled,
        cash_avail=cash_avail,
        interest_avail=interest_avail,
        principal_avail=principal_avail,
        collateral_by_group=collateral_by_group,
        cash_avail_by_group=cash_avail_by_group,
        interest_avail_by_group=interest_avail_by_group,
        principal_avail_by_group=principal_avail_by_group,
        trace_buf=trace_buf,
    )
    # Pre-allocate any virtual streams declared by SPLIT_CASH targets that are
    # not already bonds/accounts/fees/built-ins/source_formulas. These streams
    # are decrementable per-period arrays just like the built-in cash streams.
    _builtin_stream_names = {
        "CASH", "COLLATERAL", "LOSS", "INT_CASH", "PRIN_CASH",
    }
    _known_account_or_bond_or_fee = (
        set(bonds.keys()) | set(accounts.keys()) | set(fee_defs_by_name.keys())
    )
    for rule in compiled:
        if rule.tag != _OP_SPLIT_CASH:
            continue
        for name in rule.target_names:
            if (
                name in _builtin_stream_names
                or name in _known_account_or_bond_or_fee
                or name in ctx.virtual_sources
            ):
                continue
            ctx.virtual_sources[name] = np.zeros(cf_len)

    for i in range(1, cf_len):
        update_bonds_pre_ws(bonds, i)
        for acct in accounts.values():
            acct.balance[i] = acct.balance[i - 1]
        cash_avail[i] = collateral["cashflow"][i]
        interest_avail[i] = collateral["interest"][i]
        principal_avail[i] = collateral["principal"][i]
        # Per-group cash arrays mirror the same period-fill pattern so
        # rules that route via ``GROUP_<id>_*`` source tokens see the
        # right group's cashflow stream and never cross-feed each other.
        for gid, gcoll in ctx.collateral_by_group.items():
            if i < len(gcoll["cashflow"]):
                ctx.cash_avail_by_group[gid][i] = gcoll["cashflow"][i]
                ctx.interest_avail_by_group[gid][i] = gcoll["interest"][i]
                ctx.principal_avail_by_group[gid][i] = gcoll["principal"][i]

        # Z-bond accrual pre-waterfall step: capitalize unpaid coupon into Z balance
        # and pay an equal amount as principal to the support tranche stack. This
        # implements industry-standard Z behavior where the support burns down from
        # accruing Z interest until the support is exhausted.
        _apply_z_accrual(ctx, i)

        expr_ctx = _build_expr_context(
            deal,
            run_input,
            collateral,
            bonds,
            accounts,
            ctx.trigger_states,
            ctx.calculation_values,
            ctx.virtual_sources,
            ctx.cash_avail,
            i,
            orig_collat_bal,
        )
        ctx.calculation_values = _evaluate_calculations(deal, expr_ctx)
        if deal.triggers:
            _evaluate_triggers(deal, ctx, i, orig_collat_bal, cum_loss_cache)
        _update_virtual_sources(deal, ctx, run_input, i, orig_collat_bal)
        expr_ctx = _build_expr_context(
            deal,
            run_input,
            collateral,
            bonds,
            accounts,
            ctx.trigger_states,
            ctx.calculation_values,
            ctx.virtual_sources,
            ctx.cash_avail,
            i,
            orig_collat_bal,
        )
        allow_negative_cash_math = bool(deal.deal_knobs.get("allow_negative_cashflow_math", False))
        # Reset per-period cash snapshots so each rule sees the cash state as
        # of its own start, anchored to a deterministic point in the waterfall.
        ctx.rule_cash_snapshots.clear()

        for rule in compiled:
            # Capture the cash level on each stream immediately before this
            # rule executes so later rules can reference it in their
            # `max_amount_expr`. The exposed identifiers are:
            #   `cash_at_<rule_id>`       - combined CASH stream
            #   `prin_cash_at_<rule_id>`  - PRIN_CASH stream (pool principal)
            #   `int_cash_at_<rule_id>`   - INT_CASH stream (pool interest)
            # Face-weighted percentage splits (e.g., FNR 2006-018 supports
            # 95.65 / 4.35) anchor against the same stream they actually
            # draw from so the cap proportions and the consumed cash refer
            # to the same dollar pool.
            ctx.rule_cash_snapshots[rule.rule_id] = (
                float(ctx.cash_avail[i]) if ctx.cash_avail is not None else 0.0
            )
            if ctx.principal_avail is not None:
                ctx.rule_cash_snapshots[f"__prin__:{rule.rule_id}"] = float(
                    ctx.principal_avail[i]
                )
            if ctx.interest_avail is not None:
                ctx.rule_cash_snapshots[f"__int__:{rule.rule_id}"] = float(
                    ctx.interest_avail[i]
                )
            rule_expr_ctx = _build_expr_context(
                deal,
                run_input,
                collateral,
                bonds,
                accounts,
                ctx.trigger_states,
                ctx.calculation_values,
                ctx.virtual_sources,
                ctx.cash_avail,
                i,
                orig_collat_bal,
            )
            for snap_rule_id, snap_value in ctx.rule_cash_snapshots.items():
                # Snapshot identifiers are namespaced: bare rule_id → CASH,
                # `__prin__:<rule_id>` → PRIN_CASH, `__int__:<rule_id>` → INT_CASH.
                if snap_rule_id.startswith("__prin__:"):
                    base = snap_rule_id[len("__prin__:"):]
                    key = f"prin_cash_at_{base}"
                elif snap_rule_id.startswith("__int__:"):
                    base = snap_rule_id[len("__int__:"):]
                    key = f"int_cash_at_{base}"
                else:
                    key = f"cash_at_{snap_rule_id}"
                if key.isidentifier():
                    rule_expr_ctx[key] = snap_value
            if rule.condition_trigger:
                trig_active = ctx.trigger_states.get(rule.condition_trigger, False)
                if rule.condition_invert:
                    trig_active = not trig_active
                if not trig_active:
                    continue
            if rule.condition_expr:
                if _safe_eval_expr(rule.condition_expr, rule_expr_ctx) <= 0.0:
                    continue

            max_amt = _resolve_rule_max_amount(rule, rule_expr_ctx, ctx.calculation_values)
            sources = _resolve_source_arrays(ctx, rule.source_keys)

            if rule.tag == _OP_SPLIT_CASH:
                # Cash plumbing: drain the input streams (sum across `sources`),
                # then load each target stream with `weight_i * total_in`.
                # Supports both 1->N (split) and N->1 (merge) shapes:
                #
                #   1->N split:  sources=[parent], targets=[a, b, ...],
                #                weights=[wa, wb, ...]; each target gets
                #                wi * parent_value, parent loses sum(wi)*pv.
                #   N->1 merge:  sources=[a, b, ...], targets=[combined],
                #                weights=[1.0]; combined gets sum(sources).
                #
                # When max_amount is set, that value caps the total amount
                # drained from the input streams this period (use cases:
                # transfer up to X dollars; throttle a dynamic split).
                weights = rule.target_weights or tuple(
                    1.0 / len(rule.target_names) for _ in rule.target_names
                )
                # Total cash currently available across all input sources.
                total_in = float(sum(float(src[i]) for src in sources))
                if max_amt is not None:
                    total_in = min(total_in, float(max_amt))
                if total_in <= 0.0:
                    if trace_buf is not None:
                        for tgt_name, w in zip(rule.target_names, weights):
                            trace_buf.append(
                                (
                                    scenario_name, i, rule.rule_id, rule.order,
                                    rule.rule_type_str,
                                    ",".join(rule.source_keys), tgt_name,
                                    float(w * total_in), 0.0, 0.0, 0.0,
                                    rule.condition_trigger,
                                    ctx.trigger_states.get(rule.condition_trigger)
                                    if rule.condition_trigger else None,
                                )
                            )
                    continue
                # Drain each input proportionally to its current contribution
                # so input streams empty in lockstep (avoids one source going
                # negative when others are still positive).
                source_totals = [float(src[i]) for src in sources]
                grand_total = float(sum(source_totals))
                if grand_total > 0.0:
                    for src, src_total in zip(sources, source_totals):
                        share = total_in * (src_total / grand_total)
                        src[i] = float(src[i]) - share
                # Allocate to targets by weight. Targets are virtual streams
                # (already pre-allocated in ctx.virtual_sources for SPLIT_CASH
                # outputs). For convenience also support targets that are
                # built-in streams (CASH/INT_CASH/PRIN_CASH) so a sweep-back
                # can return cash to a built-in source.
                for tgt_name, w in zip(rule.target_names, weights):
                    out = float(w * total_in)
                    target_arr: np.ndarray | None
                    if tgt_name == "CASH" or tgt_name == "COLLATERAL":
                        target_arr = ctx.cash_avail
                    elif tgt_name == "INT_CASH":
                        target_arr = ctx.interest_avail
                    elif tgt_name == "PRIN_CASH":
                        target_arr = ctx.principal_avail
                    elif tgt_name in ctx.virtual_sources:
                        target_arr = ctx.virtual_sources[tgt_name]
                    elif tgt_name in bonds:
                        # Direct deposit to a bond's principal output (rare
                        # but useful for "transfer X to bond Y" plumbing).
                        target_arr = None
                        bonds[tgt_name].principal[i] += out
                        bonds[tgt_name].balance[i] = max(
                            0.0, float(bonds[tgt_name].balance[i]) - out
                        )
                    elif tgt_name in accounts:
                        target_arr = accounts[tgt_name].balance
                        accounts[tgt_name].deposit[i] += out
                    else:
                        target_arr = None
                    if target_arr is not None:
                        target_arr[i] = float(target_arr[i]) + out
                    if trace_buf is not None:
                        trace_buf.append(
                            (
                                scenario_name, i, rule.rule_id, rule.order,
                                rule.rule_type_str,
                                ",".join(rule.source_keys), tgt_name,
                                float(w * total_in), out, 0.0, 0.0,
                                rule.condition_trigger,
                                ctx.trigger_states.get(rule.condition_trigger)
                                if rule.condition_trigger else None,
                            )
                        )
                continue

            if rule.payment_style == "PRO_RATA" and rule.tag == _OP_PRINCIPAL and len(rule.target_names) > 1:
                active_targets = [(name, bonds[name]) for name in rule.target_names if name in bonds]
                avail_cash = float(min(src[i] for src in sources)) if sources else 0.0
                if max_amt is not None:
                    avail_cash = min(avail_cash, float(max_amt))
                # Schedule-first cap: PAC/TAC bonds limit themselves to their
                # remaining schedule for this period; non-scheduled bonds keep
                # their balance as the natural cap. The `ignore_schedule_cap`
                # rule flag bypasses this cap so cleanup rules ("to Aggregate
                # Group X to zero") can pay PAC bonds beyond the published
                # schedule once supports are exhausted.
                due_by_target: list[tuple[str, float]] = []
                for name, tgt in active_targets:
                    natural = max(0.0, float(tgt.balance[i]))
                    if not rule.ignore_schedule_cap:
                        sched_remaining = _schedule_remaining(tgt, i)
                        if sched_remaining is not None:
                            natural = min(natural, sched_remaining)
                    due_by_target.append((name, natural))
                total_due = float(sum(d for _, d in due_by_target))
                remaining = max(0.0, avail_cash)
                paid_by_target: dict[str, float] = {name: 0.0 for name, _ in active_targets}

                if remaining > 0.0 and total_due > 0.0:
                    nonzero = [name for name, due in due_by_target if due > 0.0]
                    last_nonzero = nonzero[-1] if nonzero else None
                    for name, due in due_by_target:
                        if due <= 0.0 or remaining <= 0.0:
                            continue
                        if name == last_nonzero:
                            alloc = min(due, remaining)
                        else:
                            alloc = min(due, avail_cash * (due / total_due))
                        alloc = max(0.0, min(alloc, remaining, due))
                        if alloc <= 0.0:
                            continue
                        tgt = bonds[name]
                        tgt.principal[i] += alloc
                        tgt.balance[i] -= alloc
                        for src in sources:
                            src[i] -= alloc
                        remaining -= alloc
                        paid_by_target[name] = alloc

                if trace_buf is not None:
                    for name in rule.target_names:
                        if name not in bonds:
                            continue
                        trace_buf.append(
                            (
                                scenario_name,
                                i,
                                rule.rule_id,
                                rule.order,
                                rule.rule_type_str,
                                ",".join(rule.source_keys),
                                name,
                                max_amt or 0.0,
                                paid_by_target.get(name, 0.0),
                                0.0,
                                0.0,
                                rule.condition_trigger,
                                ctx.trigger_states.get(rule.condition_trigger) if rule.condition_trigger else None,
                            )
                        )
                continue

            # `max_amt` is a SHARED cap across all targets in this rule, not a
            # per-target cap. We track cumulative consumption so a multi-target
            # SEQUENTIAL rule (e.g. "95.65% of cash sequentially to WA->WG")
            # cannot exceed the rule's overall budget when the source happens
            # to be smaller than the cap. Without this, a small source gets
            # fully drained by the first targets of a sequential cascade and
            # later parallel rules (the 4.35% bucket to PO) see an empty
            # source even though the prospectus intends a face-weighted split.
            shared_cap_remaining = max_amt
            for tgt_name in rule.target_names:
                tgt = bonds.get(tgt_name)
                acct_tgt = accounts.get(tgt_name)
                if tgt is None and acct_tgt is None:
                    continue
                # When a shared cap is active, derive the per-target ceiling
                # from what's left of it; otherwise pass `max_amt` through
                # unchanged so single-target rules and rules without a cap
                # behave as before.
                target_max_amt = (
                    shared_cap_remaining if max_amt is not None else None
                )

                pmt = 0.0
                if tgt is None and acct_tgt is not None and rule.tag == _OP_TO_RESERVE:
                    pmt = pay_to_reserve(sources, acct_tgt.balance, acct_tgt.withdrawal, i, max_amount=target_max_amt if target_max_amt is not None else 0.0)
                    acct_tgt.deposit[i] += pmt
                    acct_tgt.withdrawal[i] = max(0.0, acct_tgt.withdrawal[i] - pmt)
                elif tgt is not None:
                    if rule.tag == _OP_INTEREST:
                        pmt = pay_interest(
                            sources,
                            tgt.interest,
                            tgt.opt_interest,
                            tgt.int_shortfall,
                            i,
                            max_amount=target_max_amt,
                            allow_negative=allow_negative_cash_math,
                        )
                    elif rule.tag == _OP_INTEREST_SF:
                        pmt = pay_interest(
                            sources,
                            tgt.interest,
                            tgt.opt_interest,
                            tgt.int_shortfall,
                            i,
                            max_amount=target_max_amt,
                            shortfall=True,
                            allow_negative=allow_negative_cash_math,
                        )
                    elif rule.tag == _OP_PRINCIPAL:
                        # Schedule-first cap composes with rule-level cap so PAC/TAC bonds
                        # never exceed their published principal contract for this period,
                        # unless the rule sets `ignore_schedule_cap` (cleanup-rule pattern).
                        if rule.ignore_schedule_cap:
                            effective_max = target_max_amt
                        else:
                            effective_max = _effective_principal_cap(tgt, i, target_max_amt)
                        pmt = pay_principal(
                            sources,
                            tgt.principal,
                            tgt.balance,
                            i,
                            max_amount=effective_max,
                            allow_negative=allow_negative_cash_math,
                        )
                    elif rule.tag == _OP_WRITEDOWN:
                        pmt = pay_writedown(
                            sources,
                            tgt.writedown,
                            tgt.balance,
                            i,
                            max_amount=target_max_amt,
                            allow_negative=allow_negative_cash_math,
                        )
                    elif rule.tag == _OP_FEE:
                        collateral_balance_start = collateral["balance"][i - 1] if i > 0 else collateral["balance"][0]
                        fee_due = _resolve_fee_due_amount(
                            fee_defs_by_name.get(tgt_name),
                            run_input,
                            float(collateral_balance_start),
                            i,
                            {**rule_expr_ctx, **ctx.calculation_values},
                        )
                        if target_max_amt is not None and fee_due > 0.0:
                            fee_due = min(fee_due, target_max_amt)
                        elif target_max_amt is not None and fee_due <= 0.0:
                            fee_due = target_max_amt
                        if rule.allow_negative_source:
                            pmt = max(0.0, fee_due)
                            tgt.interest[i] += pmt
                            for src in sources:
                                src[i] -= pmt
                        else:
                            pmt = pay_fee(
                                sources,
                                tgt.interest,
                                i,
                                fee_due,
                                allow_negative=allow_negative_cash_math,
                            )
                    elif rule.tag == _OP_RESIDUAL:
                        pmt = pay_residual(
                            sources,
                            tgt.interest,
                            i,
                            target_max_amt,
                            allow_negative=allow_negative_cash_math,
                        )
                    elif rule.tag == _OP_TO_RESERVE:
                        pmt = pay_to_reserve(sources, tgt.balance, tgt.principal, i, max_amount=target_max_amt if target_max_amt is not None else 0.0)
                    elif rule.tag == _OP_FROM_RESERVE_INT:
                        if rule.reserve_name and rule.reserve_name in bonds:
                            rsv = bonds[rule.reserve_name]
                            pmt = pay_interest_from_reserve([], tgt.interest, tgt.opt_interest, tgt.int_shortfall, rsv.balance, rsv.principal, i, max_amount=target_max_amt)
                        elif rule.reserve_name and rule.reserve_name in accounts:
                            rsv_a = accounts[rule.reserve_name]
                            pmt = pay_interest_from_reserve([], tgt.interest, tgt.opt_interest, tgt.int_shortfall, rsv_a.balance, rsv_a.withdrawal, i, max_amount=target_max_amt)
                            rsv_a.withdrawal[i] += pmt
                    elif rule.tag == _OP_FROM_RESERVE_PRIN:
                        if rule.reserve_name and rule.reserve_name in bonds:
                            rsv = bonds[rule.reserve_name]
                            pmt = pay_principal_from_reserve([], tgt.principal, tgt.balance, rsv.balance, rsv.principal, i, max_amount=target_max_amt)
                        elif rule.reserve_name and rule.reserve_name in accounts:
                            rsv_a = accounts[rule.reserve_name]
                            pmt = pay_principal_from_reserve([], tgt.principal, tgt.balance, rsv_a.balance, rsv_a.withdrawal, i, max_amount=target_max_amt)
                            rsv_a.withdrawal[i] += pmt
                    elif rule.tag == _OP_FROM_RESERVE:
                        if rule.reserve_name and rule.reserve_name in bonds:
                            rsv = bonds[rule.reserve_name]
                            pmt = pay_from_reserve([], tgt.interest, rsv.balance, rsv.principal, i, target_max_amt)
                        elif rule.reserve_name and rule.reserve_name in accounts:
                            rsv_a = accounts[rule.reserve_name]
                            pmt = pay_from_reserve([], tgt.interest, rsv_a.balance, rsv_a.withdrawal, i, target_max_amt)
                            rsv_a.withdrawal[i] += pmt
                    elif rule.tag == _OP_RECOURSE_INT and len(rule.source_keys) == 1 and rule.source_keys[0] in bonds:
                        src_bond = bonds[rule.source_keys[0]]
                        pmt = pay_recourse_interest(src_bond.principal, src_bond.balance, tgt.interest, tgt.opt_interest, tgt.int_shortfall, i)
                    elif rule.tag == _OP_RECOURSE_PRIN and len(rule.source_keys) == 1 and rule.source_keys[0] in bonds:
                        src_bond = bonds[rule.source_keys[0]]
                        rec_amt = max_amt or 0.0
                        pmt = pay_recourse_principal(src_bond.principal, src_bond.balance, tgt.principal, tgt.balance, i, rec_amt)

                if trace_buf is not None:
                    trace_buf.append(
                        (
                            scenario_name,
                            i,
                            rule.rule_id,
                            rule.order,
                            rule.rule_type_str,
                            ",".join(rule.source_keys),
                            tgt_name,
                            max_amt or 0.0,
                            pmt,
                            0.0,
                            0.0,
                            rule.condition_trigger,
                            ctx.trigger_states.get(rule.condition_trigger) if rule.condition_trigger else None,
                        )
                    )

                # Decrement the rule's shared cap so subsequent targets in
                # this loop iteration see only the remaining budget.
                if shared_cap_remaining is not None and pmt > 0.0:
                    shared_cap_remaining = max(0.0, shared_cap_remaining - float(pmt))

        # PIK bonds capitalize unpaid coupon accrual into balance during accrual windows.
        # Z-behavior bonds were already processed in `_apply_z_accrual` pre-waterfall
        # (interest accrued AND used to pay support principal). For non-Z PIK bonds,
        # opt_interest still carries the accrual amount and is capitalized here.
        for ws in bonds.values():
            if ws.pay_mode != "PIK":
                continue
            if ws.tranche_behavior == "Z" and ws.z_accrual_enabled and not ws.z_released:
                # Already handled pre-waterfall; opt_interest was zeroed.
                continue
            pik_accrual = max(0.0, float(ws.opt_interest[i]))
            if pik_accrual <= 0.0:
                continue
            ws.balance[i] += pik_accrual
            ws.opt_interest[i] = 0.0
            ws.int_shortfall[i] = 0.0
        _apply_balance_trackers(deal, ctx, run_input, i, orig_collat_bal)
        update_bonds_post_ws(bonds, i)

    for ws in bonds.values():
        finalize_bond_ws(ws, ws.is_pseudo, ws.is_bond)

    bond_cf_rows: list[BondCashflowRow] = []
    for ws in bonds.values():
        for p in range(cf_len):
            bond_cf_rows.append(
                BondCashflowRow(
                    scenario_name=scenario_name,
                    tranche_id=ws.name,
                    period=p,
                    begin_balance=float(ws.balance[p - 1]) if p > 0 else float(ws.balance[0]),
                    total_principal=float(ws.principal[p]),
                    interest_due=float(ws.opt_interest[p]),
                    interest_paid=float(ws.interest[p]),
                    interest_shortfall=float(ws.int_shortfall[p]),
                    writedown=float(ws.writedown[p]),
                    end_balance=float(ws.balance[p]),
                    cashflow_total=float(ws.cashflow[p]),
                    coupon_rate=float(ws.coupons[p]),
                )
            )

    account_rows: list[DealAccountRow] = []
    for ws in accounts.values():
        for p in range(cf_len):
            account_rows.append(
                DealAccountRow(
                    scenario_name=scenario_name,
                    account_id=ws.name,
                    account_type=ws.account_type,
                    period=p,
                    begin_balance=float(ws.balance[p - 1]) if p > 0 else float(ws.balance[0]),
                    deposit=float(ws.deposit[p]),
                    withdrawal=float(ws.withdrawal[p]),
                    end_balance=float(ws.balance[p]),
                    required_minimum=float(ws.required_minimum[p]),
                    minimum_basis=ws.minimum_basis,
                    breach_flag=bool(ws.balance[p] < ws.required_minimum[p]),
                )
            )

    trace_rows: list[WaterfallTraceRow] = []
    if trace_buf:
        for t in trace_buf:
            trace_rows.append(
                WaterfallTraceRow(
                    scenario_name=t[0],
                    period=t[1],
                    rule_id=t[2],
                    rule_order=t[3],
                    rule_type=t[4],
                    from_source=t[5],
                    to_target=t[6],
                    amount_requested=t[7],
                    amount_paid=t[8],
                    remaining_source=t[9],
                    remaining_obligation=t[10],
                    condition_id=t[11],
                    condition_result=t[12],
                )
            )

    pac_tac_rows, structure_rows = build_tranche_behavior_diagnostics(
        deal,
        scenario_name=scenario_name,
        bond_cashflows=bond_cf_rows,
    )

    return ScenarioOutputBundle(
        scenario_name=scenario_name,
        bond_cashflows=bond_cf_rows,
        deal_accounts=account_rows,
        waterfall_trace=trace_rows,
        trigger_state_history=ctx.trigger_rows,
        pac_tac_diagnostics=pac_tac_rows,
        structure_composition=structure_rows,
    )
