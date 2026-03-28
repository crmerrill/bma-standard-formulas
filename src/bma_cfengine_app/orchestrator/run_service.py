from __future__ import annotations

import time
import traceback
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from bma_standard_formulas.engine import (
    Loan,
    PortfolioCashflow,
    TapeSchema,
    build_expanded_price_yield_table,
    build_price_yield_table,
    compute_risk_metrics,
    read_loan_tape,
    run_actual_portfolio,
    run_paired_portfolio,
    run_scheduled_portfolio,
)

from ..api.models import (
    REQUIRED_FIELDS,
    AssumptionsPayload,
    CashflowPreview,
    FieldMapping,
    GroupingConfig,
    PriceYieldTableResult,
    RiskMetricsResult,
    RiskResponse,
    RunResponse,
    RunStatus,
    RunSummary,
    TapeStats,
)
from ..storage import run_store
from .assumptions_resolver import resolve_portfolio_curves
from .grouping import compute_group_ids
from .mapping import apply_mapping
from .rates import build_rate_index_from_file, rates_preflight

INT_FIELDS = {
    "loan_id", "original_term", "remaining_term",
    "advance_months", "reset_frequency",
}


def _coerce_int_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in df.columns:
        if col not in INT_FIELDS:
            continue
        if df[col].dtype.kind == "f":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return df


def _dedup_cols(df: pd.DataFrame) -> pd.DataFrame:
    if df.columns.has_duplicates:
        return df.loc[:, ~df.columns.duplicated()]
    return df


def _run_portfolio(
    loans: list[Loan],
    smm: Any, mdr: Any, severity: Any,
    sev_lag: int, months_liq: int,
    rate_index: Any, run_mode: str,
) -> PortfolioCashflow:
    if run_mode == "scheduled":
        return run_scheduled_portfolio(loans, rate_index=rate_index, flush=True)
    elif run_mode == "paired":
        return run_paired_portfolio(
            loans, smm, mdr, severity,
            rate_index=rate_index,
            severity_lag=sev_lag, months_to_liquidation=months_liq, flush=True,
        )
    else:
        return run_actual_portfolio(
            loans, smm, mdr, severity,
            rate_index=rate_index,
            severity_lag=sev_lag, months_to_liquidation=months_liq, flush=True,
        )


def compute_tape_stats(df: pd.DataFrame) -> TapeStats:
    bal_col = "current_balance" if "current_balance" in df.columns else None
    rate_col = "rate_margin" if "rate_margin" in df.columns else None
    rem_col = "remaining_term" if "remaining_term" in df.columns else None
    orig_col = "original_term" if "original_term" in df.columns else None

    total_bal = float(df[bal_col].sum()) if bal_col else 0.0
    bals = df[bal_col] if bal_col else pd.Series(dtype=float)

    wac = float((df[rate_col] * bals).sum() / total_bal) if rate_col and bal_col and total_bal > 0 else 0.0
    wam = float((df[rem_col] * bals).sum() / total_bal) if rem_col and bal_col and total_bal > 0 else 0.0

    if orig_col and rem_col and bal_col and total_bal > 0:
        wala = float(((df[orig_col] - df[rem_col]) * bals).sum() / total_bal)
    else:
        wala = 0.0

    rate_dist: dict[str, int] = {}
    if "index_type" in df.columns:
        for val, cnt in df["index_type"].value_counts().items():
            rate_dist[str(val)] = int(cnt)
    fixed_count = len(df) - sum(rate_dist.values())
    if fixed_count > 0:
        rate_dist["Fixed"] = fixed_count

    return TapeStats(
        record_count=len(df),
        total_balance=total_bal,
        wac=round(wac, 4),
        wala=round(wala, 1),
        wam=round(wam, 1),
        coupon_min=float(df[rate_col].min()) if rate_col else 0.0,
        coupon_max=float(df[rate_col].max()) if rate_col else 0.0,
        balance_min=float(bals.min()) if bal_col and len(bals) else 0.0,
        balance_max=float(bals.max()) if bal_col and len(bals) else 0.0,
        rate_type_distribution=rate_dist,
    )


def _safe_artifact_name(name: str) -> str:
    import re
    safe = re.sub(r'[^\w\-.]', '_', name)
    return safe[:80]


def _execute_single_scenario(
    run_id: str,
    scenario_name: str,
    loans: list[Loan],
    groups_by_id: dict[str, list[Loan]],
    group_id_map: dict[int, str] | None,
    assumptions: AssumptionsPayload,
    run_mode: str,
    rate_index: Any,
    grouping: GroupingConfig | None,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Run one scenario. Returns (sections, group_names, group_artifact_map)."""
    prefix = _safe_artifact_name(scenario_name)

    smm, mdr, severity, sev_lag, months_liq = resolve_portfolio_curves(
        loans, assumptions, group_id_map
    )

    portfolio = _run_portfolio(loans, smm, mdr, severity, sev_lag, months_liq, rate_index, run_mode)

    actual_df = _dedup_cols(portfolio.to_dataframe())
    run_store.save_artifact(run_id, f"{prefix}_portfolio_actual", actual_df)
    run_store.save_artifact_csv(run_id, f"{prefix}_portfolio_actual", actual_df)

    if run_mode in ("paired", "scheduled"):
        try:
            from bma_standard_formulas.formulas.cashflows import BMAScheduledCashflow
            sch = portfolio.scheduled
            sch_df = pd.DataFrame({f.name: getattr(sch, f.name) for f in sch.__dataclass_fields__.values()
                                   if isinstance(getattr(sch, f.name), np.ndarray)})
            sch_df = _dedup_cols(sch_df)
            run_store.save_artifact(run_id, f"{prefix}_portfolio_scheduled", sch_df)
            run_store.save_artifact_csv(run_id, f"{prefix}_portfolio_scheduled", sch_df)
        except Exception:
            pass

    sections = [f"{prefix}_portfolio_actual"]
    group_names: list[str] = []
    group_artifact_map: dict[str, str] = {}

    if grouping and groups_by_id:
        for gid, group_loans in sorted(groups_by_id.items()):
            try:
                gp = _run_portfolio(group_loans, smm, mdr, severity, sev_lag, months_liq, rate_index, run_mode)
                gdf = _dedup_cols(gp.to_dataframe())
                gname = _safe_artifact_name(gid)
                artifact_key = f"{prefix}_group_{gname}_actual"
                run_store.save_artifact(run_id, artifact_key, gdf)
                run_store.save_artifact_csv(run_id, artifact_key, gdf)
                group_names.append(gid)
                group_artifact_map[gid] = artifact_key

                if run_mode in ("paired", "scheduled"):
                    try:
                        gsch = gp.scheduled
                        gsch_df = pd.DataFrame({f.name: getattr(gsch, f.name) for f in gsch.__dataclass_fields__.values()
                                                if isinstance(getattr(gsch, f.name), np.ndarray)})
                        gsch_df = _dedup_cols(gsch_df)
                        run_store.save_artifact(run_id, f"{prefix}_group_{gname}_scheduled", gsch_df)
                        run_store.save_artifact_csv(run_id, f"{prefix}_group_{gname}_scheduled", gsch_df)
                    except Exception:
                        pass
            except Exception:
                pass

    return sections, group_names, group_artifact_map


def execute_run(
    run_id: str,
    upload_id: str,
    mappings: list[FieldMapping],
    asof_date: str | None,
    grouping: GroupingConfig | None,
    assumptions: AssumptionsPayload,
    run_mode: str,
    include_period_zero: bool = False,
    scenarios: list[dict[str, Any]] | None = None,
) -> RunResponse:
    created_at = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    try:
        run_store.save_manifest(run_id, {"status": "running", "upload_id": upload_id})

        df_raw, _ = run_store.load_upload_df(upload_id)
        df_mapped = _dedup_cols(apply_mapping(df_raw, mappings))
        df_mapped = _coerce_int_columns(df_mapped)

        column_map = {m.source_column: m.canonical_field for m in mappings}
        schema = TapeSchema(column_map)
        loans = schema.read(df_mapped, asof_date=asof_date or None)

        if not loans:
            raise ValueError("Tape produced zero loans after parsing")

        group_id_map: dict[int, str] | None = None
        groups_by_id: dict[str, list[Loan]] = {}
        group_count = 1
        if grouping:
            group_series = compute_group_ids(df_raw, grouping)
            group_id_map = {}
            for i, loan in enumerate(loans):
                gid = str(group_series.iloc[i])
                loan.group_id = gid
                group_id_map[loan.loan_id] = gid
                groups_by_id.setdefault(gid, []).append(loan)
            group_count = len(groups_by_id)

        rate_index = None
        pf = rates_preflight(upload_id)
        if not pf.all_fixed and pf.resolved_mapping:
            rate_index = build_rate_index_from_file(upload_id, pf.resolved_mapping)

        scenario_list = scenarios or [
            {"name": "Base Case", "assumptions": assumptions.model_dump(), "run_mode": run_mode}
        ]

        all_sections: list[str] = []
        all_group_names: list[str] = []
        all_group_artifacts: dict[str, str] = {}
        scenario_names: list[str] = []

        for sc_spec in scenario_list:
            sc_name = sc_spec.get("name", "Base Case")
            raw_assumptions = sc_spec["assumptions"]
            if "portfolio_defaults" in raw_assumptions:
                sc_assumptions = AssumptionsPayload(**raw_assumptions)
            else:
                sc_assumptions = AssumptionsPayload(portfolio_defaults=AssumptionSet(**raw_assumptions))
            sc_run_mode = sc_spec.get("run_mode", run_mode)

            sections, gnames,gart_map = _execute_single_scenario(
                run_id, sc_name, loans, groups_by_id, group_id_map,
                sc_assumptions, sc_run_mode, rate_index, grouping,
            )
            all_sections.extend(sections)
            scenario_names.append(sc_name)
            if gnames and not all_group_names:
                all_group_names = gnames
            all_group_artifacts.update(gart_map)

        if all_group_names:
            all_sections.append("group_cashflows")

        elapsed_sec = round(time.perf_counter() - t_start, 3)

        total_bal = sum(l.current_balance for l in loans)
        wac = sum(l.rate_margin * l.current_balance for l in loans) / total_bal if total_bal else 0.0
        wam = sum(l.remaining_term * l.current_balance for l in loans) / total_bal if total_bal else 0.0

        summary = RunSummary(
            loan_count=len(loans),
            group_count=group_count,
            total_balance=total_bal,
            wac=round(wac, 4),
            wam=round(wam, 1),
            elapsed_seconds=elapsed_sec,
        )

        scenarios_manifest = [
            {"name": sc.get("name"), "run_mode": sc.get("run_mode"),
             "assumptions": sc.get("assumptions")}
            for sc in scenario_list
        ]

        run_store.save_manifest(run_id, {
            "status": "completed",
            "upload_id": upload_id,
            "loan_count": len(loans),
            "group_count": group_count,
            "sections": all_sections,
            "group_names": all_group_names,
            "group_artifacts": all_group_artifacts,
            "scenario_names": scenario_names,
            "scenarios": scenarios_manifest,
            "elapsed_seconds": elapsed_sec,
            "summary": summary.model_dump(),
        })

        return RunResponse(
            run_id=run_id, status=RunStatus.completed, created_at=created_at,
            summary=summary, sections=all_sections,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        run_store.save_manifest(run_id, {
            "status": "failed", "error": error_msg, "traceback": traceback.format_exc(),
        })
        return RunResponse(run_id=run_id, status=RunStatus.failed, created_at=created_at, error=error_msg)


def execute_risk(
    run_id: str,
    analytics: list[str],
    input_kind: str,
    base_value: float = 6.0,
    column_inputs: list[float] | None = None,
) -> RiskResponse:
    """Compute risk analytics for portfolio and each group using actual cashflow data."""
    manifest = run_store.load_manifest(run_id)
    if manifest.get("status") != "completed":
        raise ValueError(f"Run {run_id} is not completed")

    from bma_standard_formulas.formulas.cashflows import run_bma_scheduled_cashflow

    summary = manifest.get("summary", {})
    group_names = manifest.get("group_names", [])
    group_artifacts = manifest.get("group_artifacts", {})
    scenario_names = manifest.get("scenario_names", ["Base Case"])
    first_scenario = _safe_artifact_name(scenario_names[0]) if scenario_names else "Base_Case"

    def _make_proxy_cf(bal: float, wac_val: float, wam_val: int):
        return run_bma_scheduled_cashflow(
            original_balance=bal, current_balance=bal,
            coupon_vector=wac_val, original_term=max(int(wam_val), 12), remaining_term=max(int(wam_val), 12),
        )

    scenarios: dict[str, Any] = {}

    # Portfolio: use WAC proxy for risk (actual CF doesn't have a single yield to solve from)
    scenarios["Portfolio"] = _make_proxy_cf(
        summary.get("total_balance", 100_000.0),
        summary.get("wac", 6.0),
        int(summary.get("wam", 360)),
    )

    # Groups: compute WAC/WAM/balance from group artifacts for proper risk
    for gname in group_names:
        artifact_key = group_artifacts.get(gname)
        if not artifact_key:
            continue
        try:
            gdf = run_store.load_artifact(run_id, artifact_key)
            if len(gdf) < 2:
                continue
            # Use the group's actual balance and estimated WAC from the cashflow
            group_bal = float(gdf.iloc[0].get("perf_bal", 0)) if "perf_bal" in gdf.columns else 100_000.0
            group_rate = float(gdf.iloc[1].get("gross_rate", summary.get("wac", 6.0))) if "gross_rate" in gdf.columns else summary.get("wac", 6.0)
            group_wam = len(gdf) - 1
            if group_bal > 0 and group_rate > 0:
                scenarios[gname] = _make_proxy_cf(group_bal, group_rate * 100 if group_rate < 1 else group_rate, group_wam)
        except (FileNotFoundError, Exception):
            pass

    from bma_standard_formulas.formulas.pricing_risk import PriceRiskAnalyzer

    if column_inputs is None:
        column_inputs = []

    result = RiskResponse(run_id=run_id)

    if "risk_metrics" in analytics:
        metrics: dict[str, RiskMetricsResult] = {}
        for label, cf in scenarios.items():
            try:
                if input_kind == "price":
                    analyzer = PriceRiskAnalyzer.from_cashflow(cf)
                    price_input = np.array([base_value], dtype=float)
                    py_table = analyzer.price_yield_table(price_input, "price")
                    solved_yield = float(py_table.values[0, 0])
                    m = compute_risk_metrics(cf, solved_yield)
                else:
                    solved_yield = base_value
                    m = compute_risk_metrics(cf, solved_yield)

                metrics[label] = RiskMetricsResult(
                    price=m.price,
                    macaulay_duration_years=m.macaulay_duration_years,
                    modified_duration_years=m.modified_duration_years,
                    convexity_years2=m.convexity_years2,
                    yield_pct=solved_yield,
                )
            except Exception:
                pass
        result.risk_metrics = metrics

    if "price_yield_table" in analytics and scenarios and column_inputs:
        inputs_arr = np.array(column_inputs, dtype=float)
        try:
            table = build_price_yield_table(
                scenarios=scenarios,
                column_inputs=inputs_arr,
                input_kind=input_kind,
            )
            result.price_yield_table = PriceYieldTableResult(
                input_kind=input_kind,
                value_kind=table.value_kind,
                scenarios=list(table.row_labels),
                column_inputs=column_inputs,
                values=table.values.tolist(),
            )
        except Exception:
            pass

    return result


def get_run_groups(run_id: str) -> tuple[list[str], dict[str, str]]:
    manifest = run_store.load_manifest(run_id)
    return manifest.get("group_names", []), manifest.get("group_artifacts", {})


def get_run_scenarios(run_id: str) -> list[str]:
    manifest = run_store.load_manifest(run_id)
    return manifest.get("scenario_names", ["Base Case"])


def get_cashflow_preview(
    run_id: str,
    section: str,
    max_rows: int = 500,
) -> CashflowPreview:
    df = run_store.load_artifact(run_id, section)
    truncated = len(df) > max_rows
    if truncated:
        df = df.head(max_rows)

    df = df.replace({np.nan: None, np.inf: None, -np.inf: None})
    rows = df.to_dict("records")
    for row in rows:
        for k, v in row.items():
            if isinstance(v, (np.integer,)):
                row[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row[k] = float(v)

    return CashflowPreview(
        section=section,
        columns=list(df.columns),
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
