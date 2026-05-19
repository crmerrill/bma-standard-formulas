"""PAC/TAC/Z runtime behavior diagnostics primitives."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from .schemas.common import ScheduleType, StructureRelation, TrancheBehavior
from .schemas.ir import DealDefinition
from .schemas.output_structuring import PacTacDiagnosticsRow, StructureCompositionRow


def build_tranche_behavior_diagnostics(
    deal: DealDefinition,
    *,
    scenario_name: str,
    bond_cashflows: list[Any],
) -> tuple[list[PacTacDiagnosticsRow], list[StructureCompositionRow]]:
    by_tranche: dict[str, list[Any]] = defaultdict(list)
    for row in bond_cashflows:
        by_tranche[str(getattr(row, "tranche_id", ""))].append(row)
    for tranche_rows in by_tranche.values():
        tranche_rows.sort(key=lambda r: int(getattr(r, "period", 0) or 0))

    pac_tac_rows: list[PacTacDiagnosticsRow] = []
    structure_rows: list[StructureCompositionRow] = []

    for bond in deal.bonds:
        rows = by_tranche.get(bond.name, [])
        if bond.tranche_behavior in {TrancheBehavior.PAC, TrancheBehavior.TAC} and rows:
            schedule_type = (
                ScheduleType.PAC if bond.tranche_behavior == TrancheBehavior.PAC else ScheduleType.TAC
            )
            # Build per-period scheduled principal from either legacy
            # `target_principal` entries or new `target_balance` entries.
            # For balance entries, principal[t] = balance[t-1] - balance[t].
            schedule_map: dict[int, float] = {}
            sorted_points = sorted(
                (p for p in bond.schedule_contract if isinstance(p, dict)),
                key=lambda p: int(p.get("period", 0) or 0),
            )
            prev_balance: float | None = None
            for point in sorted_points:
                period = int(point.get("period", 0) or 0)
                if point.get("target_principal") is not None:
                    schedule_map[period] = float(point.get("target_principal") or 0.0)
                elif point.get("target_balance") is not None:
                    cur_balance = float(point.get("target_balance") or 0.0)
                    if prev_balance is None:
                        # First entry: assume bond was at face before this period.
                        face = float(getattr(bond, "notional", 0.0) or 0.0)
                        schedule_map[period] = max(0.0, face - cur_balance)
                    else:
                        schedule_map[period] = max(0.0, prev_balance - cur_balance)
                    prev_balance = cur_balance

            initial_balance = float(getattr(rows[0], "begin_balance", 0.0) or 0.0)
            tol_bps = float(bond.schedule_tolerance_bps or 0.0)
            tol_dollars = abs(initial_balance) * tol_bps / 10000.0
            busted_period: int | None = None
            for row in rows:
                period = int(getattr(row, "period", 0) or 0)
                scheduled = float(schedule_map.get(period, 0.0))
                actual = float(getattr(row, "total_principal", 0.0) or 0.0)
                variance = actual - scheduled
                in_range = abs(variance) <= tol_dollars if tol_dollars > 0 else abs(variance) <= 1e-6
                if not in_range and busted_period is None:
                    busted_period = period
                pac_tac_rows.append(
                    PacTacDiagnosticsRow(
                        scenario_name=scenario_name,
                        tranche_id=bond.name,
                        schedule_type=schedule_type,
                        period=period,
                        scheduled_principal=scheduled,
                        actual_principal=actual,
                        schedule_variance=variance,
                        in_protected_range_flag=in_range,
                        lower_bound_psa=float(bond.pac_lower_psa or 0.0),
                        upper_bound_psa=float(
                            bond.pac_upper_psa if bond.pac_upper_psa is not None else (bond.tac_pricing_psa or 0.0)
                        ),
                        range_drift_lower_psa=float(max(0.0, -variance)),
                        range_drift_upper_psa=float(max(0.0, variance)),
                        busted_flag=not in_range,
                        busted_period=busted_period if busted_period is not None else None,
                    )
                )

        if bond.tranche_behavior == TrancheBehavior.Z and rows:
            accrued_interest = sum(float(getattr(row, "interest_shortfall", 0.0) or 0.0) for row in rows)
            for support_name in bond.supported_by_tranches or []:
                support_rows = by_tranche.get(support_name, [])
                support_principal = sum(
                    float(getattr(row, "total_principal", 0.0) or 0.0) for row in support_rows
                )
                z_principal = sum(float(getattr(row, "total_principal", 0.0) or 0.0) for row in rows)
                structure_rows.append(
                    StructureCompositionRow(
                        scenario_name=scenario_name,
                        parent_tranche_id=support_name,
                        child_tranche_id=bond.name,
                        relation_type=StructureRelation.Z_ACCRUAL,
                        notional_ratio=(
                            float(getattr(rows[0], "begin_balance", 0.0) or 0.0)
                            / float(getattr(support_rows[0], "begin_balance", 1.0) or 1.0)
                            if support_rows
                            else 0.0
                        ),
                        coupon_identity_error=accrued_interest,
                        principal_conservation_error=max(0.0, z_principal - support_principal),
                        interest_conservation_error=0.0,
                    )
                )

    return pac_tac_rows, structure_rows

