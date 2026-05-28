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
from .mapping import apply_mapping, sanitize_field_mappings
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
    # NOTE: flush=False so _pending is retained for constituent extraction
    # (_write_paired_artifact). The caller is responsible for calling
    # portfolio.flush() after extracting constituents so per-loan memory is
    # released and per-group caches are populated (required by
    # aggregate_actual_by_group and aggregate_scheduled_by_group).
    if run_mode == "scheduled":
        return run_scheduled_portfolio(loans, rate_index=rate_index, flush=False)
    elif run_mode == "paired":
        return run_paired_portfolio(
            loans, smm, mdr, severity,
            rate_index=rate_index,
            severity_lag=sev_lag, months_to_liquidation=months_liq, flush=False,
        )
    else:
        return run_actual_portfolio(
            loans, smm, mdr, severity,
            rate_index=rate_index,
            severity_lag=sev_lag, months_to_liquidation=months_liq, flush=False,
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


def _save_assumption_curves(
    run_id: str,
    prefix: str,
    smm: Any,
    mdr: Any,
    severity: Any,
    loans: list[Loan],
    group_id_map: dict[int, str] | None,
) -> str:
    """Save resolved assumption curves as parquet. Returns the format used."""
    try:
        if isinstance(smm, np.ndarray):
            horizon = len(smm)
            df = pd.DataFrame({
                "period": np.arange(horizon),
                "smm": smm,
                "mdr": mdr if isinstance(mdr, np.ndarray) else np.zeros(horizon),
                "severity": severity if isinstance(severity, np.ndarray) else np.zeros(horizon),
            })
            run_store.save_artifact(run_id, f"{prefix}_assumptions", df)
            return "portfolio"
        elif isinstance(smm, dict):
            rows = []
            for loan in loans:
                lid = loan.loan_id
                gid = group_id_map.get(lid, "") if group_id_map else ""
                s = smm.get(lid, np.array([]))
                m = mdr.get(lid, np.array([])) if isinstance(mdr, dict) else np.array([])
                sv = severity.get(lid, np.array([])) if isinstance(severity, dict) else np.array([])
                for p in range(len(s)):
                    rows.append({
                        "loan_id": lid,
                        "group_id": gid,
                        "period": p,
                        "smm": float(s[p]) if p < len(s) else 0.0,
                        "mdr": float(m[p]) if p < len(m) else 0.0,
                        "severity": float(sv[p]) if p < len(sv) else 0.0,
                    })
            if rows:
                df = pd.DataFrame(rows)
                run_store.save_artifact(run_id, f"{prefix}_assumptions", df)

                if group_id_map:
                    group_rows = []
                    seen_groups: dict[str, int] = {}
                    for loan in loans:
                        gid = group_id_map.get(loan.loan_id, "")
                        if gid in seen_groups:
                            continue
                        seen_groups[gid] = loan.loan_id
                        s = smm.get(loan.loan_id, np.array([]))
                        m = mdr.get(loan.loan_id, np.array([])) if isinstance(mdr, dict) else np.array([])
                        sv = severity.get(loan.loan_id, np.array([])) if isinstance(severity, dict) else np.array([])
                        for p in range(len(s)):
                            group_rows.append({
                                "group_id": gid,
                                "period": p,
                                "smm": float(s[p]) if p < len(s) else 0.0,
                                "mdr": float(m[p]) if p < len(m) else 0.0,
                                "severity": float(sv[p]) if p < len(sv) else 0.0,
                            })
                    if group_rows:
                        run_store.save_artifact(run_id, f"{prefix}_assumptions_by_group", pd.DataFrame(group_rows))
                    return "group"
            return "loan"
    except Exception:
        pass
    return "unknown"


def _safe_artifact_name(name: str) -> str:
    import re
    safe = re.sub(r'[^\w\-.]', '_', name)
    return safe[:80]


def _bma_actual_to_aggregate_dataframe(
    actual: Any,
    run_mode: str,
) -> pd.DataFrame:
    """Build an aggregate DataFrame for a single BMAActualCashflow.

    Mirrors the shape produced by ``PortfolioCashflow.to_dataframe()`` for
    ACTUAL_ONLY / PAIRED modes (pool fields joined with the trust waterfall),
    but operates on a pre-computed BMAActualCashflow rather than re-running
    the engine.  Used by the orchestrator to emit per-group artifacts from
    the unified portfolio's per-group aggregates without an extra engine
    invocation per group.

    The function wraps the supplied actual cashflow in a one-constituent
    PortfolioCashflow (with the same default cross-collateralization
    settings the orchestrator uses for whole-pool runs) so the existing
    waterfall computation path is reused unchanged.

    Parameters
    ----------
    actual:
        A pre-aggregated ``BMAActualCashflow`` (e.g., one entry from
        ``portfolio.aggregate_actual_by_group()``).
    run_mode:
        Run mode used by the caller. Currently informational; the returned
        DataFrame shape is identical for ``"actual"`` and ``"paired"`` (both
        produce pool + waterfall columns).
    """
    from bma_standard_formulas.engine import PortfolioCashflow
    from bma_standard_formulas.engine.portfolio import PortfolioMode

    wrapper = PortfolioCashflow([actual], mode=PortfolioMode.ACTUAL_ONLY)
    return wrapper.to_dataframe()


def _bma_scheduled_to_dataframe(scheduled: Any) -> pd.DataFrame:
    """Build a DataFrame from a single BMAScheduledCashflow.

    Mirrors the per-group scheduled artifact shape used by the pre-Phase-0B
    orchestrator (``pd.DataFrame(...)`` over each ndarray dataclass field).
    """
    return pd.DataFrame({
        f.name: getattr(scheduled, f.name)
        for f in scheduled.__dataclass_fields__.values()
        if isinstance(getattr(scheduled, f.name), np.ndarray)
    })


def _write_paired_artifact(run_id: str, artifact_name: str, constituents: list[Any]) -> None:
    """Persist per-loan BMAActualCashflow constituents directly via cashflow_persistence.

    Uses the existing Parquet-native I/O so the round-trip is lossless —
    no DataFrame conversion, no type coercion.  Each constituent is written
    as a separate row group keyed by a unique ``cf_id``.

    Constituents with an empty or shared ``cf_id`` (common when synthesized
    via adapters) are stamped with a unique UUID before writing so the
    persistence module can distinguish them on read.

    (RG2: replaces the lossy DataFrame long-format path.)
    """
    import dataclasses
    from uuid import uuid4
    from bma_standard_formulas.engine.cashflow_persistence import write_cashflow
    from ..storage import run_store as _rs

    seen_ids: set[str] = set()
    out_dir = _rs._outputs_dir(run_id)
    final_path = out_dir / f"{artifact_name}.parquet"
    # Write to a temporary file first; rename atomically on success so a
    # failed write never leaves a corrupt artifact visible to the bridge.
    tmp_path = out_dir / f"{artifact_name}.__tmp__.parquet"
    try:
        mode = "write"
        for cf in constituents:
            cf_id = getattr(cf, "cf_id", "")
            if not cf_id or cf_id in seen_ids:
                cf = dataclasses.replace(cf, cf_id=str(uuid4()))
            seen_ids.add(cf.cf_id)
            # Ensure group_id is stored as a string so that orchestrator
            # group ids like "GROUP_1" survive the cashflow_persistence
            # round-trip without being coerced to int.
            gid = getattr(cf, "group_id", None)
            if gid is not None and not isinstance(gid, str):
                cf = dataclasses.replace(cf, group_id=str(gid))
            write_cashflow(cf, path=tmp_path, mode=mode)
            mode = "append"
        tmp_path.replace(final_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _read_paired_artifact(run_id: str, artifact_name: str) -> list[Any]:
    """Load per-loan BMAActualCashflow constituents from a paired Parquet artifact.

    Returns an empty list when the artifact does not exist or is corrupt.
    Emits a UserWarning on load failure so operators can identify runs that
    need regeneration — a corrupt artifact must never silently produce a
    deal run with 0 per-loan constituents.

    (RG2: replaces the lossy DataFrame path in build_from_runsetup_ref.)
    """
    import warnings
    from bma_standard_formulas.engine.cashflow_persistence import read_actual
    from ..storage import run_store as _rs

    out_dir = _rs._outputs_dir(run_id)
    path = out_dir / f"{artifact_name}.parquet"
    if not path.exists():
        return []
    try:
        result = read_actual(path)
        if not isinstance(result, list):
            result = [result]
        return result
    except Exception as exc:
        warnings.warn(
            f"Run {run_id!r}: failed to load paired artifact {artifact_name!r}: {exc}. "
            f"Falling back to aggregate LDCMA path. Re-run the portfolio to regenerate.",
            UserWarning,
            stacklevel=2,
        )
        return []


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
    """Run one scenario. Returns (sections, group_names, group_artifact_map).

    Phase 0B refactor (May 2026): the engine is invoked exactly ONCE per
    scenario, regardless of grouping configuration. Per-group artifacts are
    derived by partitioning the resulting ``PortfolioCashflow``'s
    constituents on their ``group_id`` field via
    :meth:`PortfolioCashflow.aggregate_actual_by_group` (and
    ``aggregate_scheduled_by_group`` for paired/scheduled modes).

    Pre-Phase-0B this function ran the engine N+1 times for grouped runs
    (once for the aggregate plus once per group with a filtered loan list).
    Each per-group invocation duplicated the per-loan amortization /
    prepay / default math that the aggregate run had already performed.
    Eliminating that duplication is the primary reason for the refactor;
    the engine already supports per-loan assumption curves
    (``smm: dict[loan_id, np.ndarray]``) so a single invocation is
    sufficient to produce both the aggregate and the per-group results.

    Per-loan ``group_id`` is set on each ``Loan`` by the caller in
    :func:`execute_run` via ``loan.group_id = gid`` immediately before
    invocation here, so the engine propagates ``group_id`` into each
    constituent BMAActualCashflow / BMAScheduledCashflow. The portfolio
    flush triggered inside ``_run_portfolio`` populates the per-group
    aggregation cache as part of flush() (see Phase 0A) so per-group
    results remain available after individual constituents are released.
    """
    prefix = _safe_artifact_name(scenario_name)

    smm, mdr, severity, sev_lag, months_liq = resolve_portfolio_curves(
        loans, assumptions, group_id_map
    )

    _save_assumption_curves(run_id, prefix, smm, mdr, severity, loans, group_id_map)

    # ─── Single engine invocation across all loans ────────────────────────
    # NOTE: _run_portfolio no longer flushes so _pending is available here.
    portfolio = _run_portfolio(loans, smm, mdr, severity, sev_lag, months_liq, rate_index, run_mode)

    # Per-loan PAIRED artifact (RG2): extract constituents BEFORE flush.
    # flush() clears _pending; after that actual_constituents() returns [].
    # The artifact is written atomically (temp file + rename) so a partial
    # failure never leaves a corrupt file.
    try:
        actuals = portfolio.actual_constituents()
        if actuals:
            _write_paired_artifact(run_id, f"{prefix}_portfolio_paired", actuals)
    except Exception:
        pass  # Non-fatal: aggregate artifact is the fallback

    # Flush now: populates _committed aggregate + per-group caches, releases
    # per-loan memory. Must happen after constituent extraction above.
    portfolio.flush()

    # Whole-portfolio (aggregate) artifact — unchanged from pre-refactor
    actual_df = _dedup_cols(portfolio.to_dataframe())
    run_store.save_artifact(run_id, f"{prefix}_portfolio_actual", actual_df)
    run_store.save_artifact_csv(run_id, f"{prefix}_portfolio_actual", actual_df)


    if run_mode in ("paired", "scheduled"):
        try:
            sch = portfolio.scheduled
            sch_df = _dedup_cols(_bma_scheduled_to_dataframe(sch))
            run_store.save_artifact(run_id, f"{prefix}_portfolio_scheduled", sch_df)
            run_store.save_artifact_csv(run_id, f"{prefix}_portfolio_scheduled", sch_df)
        except Exception:
            pass

    sections = [f"{prefix}_portfolio_actual"]
    group_names: list[str] = []
    group_artifact_map: dict[str, str] = {}

    # ─── Per-group artifacts via filter+aggregate (no engine re-run) ──────
    if grouping and groups_by_id:
        # ``aggregate_actual_by_group()`` partitions the portfolio's
        # constituents by their group_id and runs _aggregate_actual on each
        # bucket. The dict is keyed by str(group_id), with "_ungrouped" used
        # for any constituents whose group_id was None (we skip that bucket
        # — those loans appear in the whole-pool aggregate but should not
        # generate a named per-group artifact).
        per_group_actuals = portfolio.aggregate_actual_by_group()
        per_group_scheduled: dict[str, Any] = {}
        if run_mode in ("paired", "scheduled"):
            try:
                per_group_scheduled = portfolio.aggregate_scheduled_by_group()
            except Exception:
                per_group_scheduled = {}

        for gid in sorted(per_group_actuals.keys()):
            if gid == "_ungrouped":
                # Ungrouped constituents are reflected in the aggregate
                # artifact only; emitting a "_ungrouped" group artifact
                # would be confusing in the UI run history.
                continue
            try:
                gactual = per_group_actuals[gid]
                gdf = _dedup_cols(_bma_actual_to_aggregate_dataframe(gactual, run_mode))
                gname = _safe_artifact_name(gid)
                artifact_key = f"{prefix}_group_{gname}_actual"
                run_store.save_artifact(run_id, artifact_key, gdf)
                run_store.save_artifact_csv(run_id, artifact_key, gdf)
                group_names.append(gid)
                group_artifact_map[gid] = artifact_key

                if run_mode in ("paired", "scheduled") and gid in per_group_scheduled:
                    try:
                        gsch = per_group_scheduled[gid]
                        gsch_df = _dedup_cols(_bma_scheduled_to_dataframe(gsch))
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
    mapping_id: str | None = None,
) -> RunResponse:
    created_at = datetime.now(timezone.utc).isoformat()
    t_start = time.perf_counter()

    try:
        run_store.save_manifest(
            run_id,
            {"status": "running", "upload_id": upload_id, "run_type": "portfolio"},
        )

        mappings = sanitize_field_mappings(mappings)

        df_raw, raw_name = run_store.load_upload_df(upload_id)

        from .rates import load_rates_df
        rates_df = load_rates_df(upload_id)

        # Load DQ mapping if it was persisted during tape intake
        dq_mapping_data: dict | None = None
        dq_mapping_path = run_store.upload_dir(upload_id) / "dq_mapping.json"
        if dq_mapping_path.exists():
            import json as _json
            dq_mapping_data = _json.loads(dq_mapping_path.read_text())

        scenario_list_early = scenarios or [
            {"name": "Base Case", "assumptions": assumptions.model_dump(), "run_mode": run_mode}
        ]
        run_store.save_run_inputs(
            run_id=run_id,
            tape_df=df_raw,
            mappings=[m.model_dump() for m in mappings],
            assumptions=assumptions.model_dump(),
            asof_date=asof_date,
            rates_df=rates_df,
            grouping=grouping.model_dump() if grouping else None,
            run_mode=run_mode,
            scenarios=scenario_list_early,
            dq_mapping=dq_mapping_data,
        )

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

        scenario_list = scenario_list_early

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

        run_config = {
            "upload_id": upload_id,
            "mapping_id": mapping_id,
            "mappings": [m.model_dump() for m in mappings],
            "asof_date": asof_date,
            "grouping": grouping.model_dump() if grouping else None,
            "run_mode": run_mode,
            "include_period_zero": include_period_zero,
        }

        run_store.save_manifest(run_id, {
            "status": "completed",
            "run_type": "portfolio",
            "upload_id": upload_id,
            "loan_count": len(loans),
            "group_count": group_count,
            "sections": all_sections,
            "group_names": all_group_names,
            "group_artifacts": all_group_artifacts,
            "scenario_names": scenario_names,
            # Persisted so build_from_runsetup_ref can set DealRunInput.original_collateral_balance
            # correctly on the PAIRED path without defaulting to 0.0.
            "original_collateral_balance": float(total_bal),
            "scenarios": scenarios_manifest,
            "elapsed_seconds": elapsed_sec,
            "summary": summary.model_dump(),
            "run_config": run_config,
            "has_inputs": True,
            "inputs": {
                "tape": "inputs/tape.parquet",
                "tape_csv": "inputs/tape.csv",
                "mappings": "inputs/mappings.json",
                "assumptions": "inputs/assumptions.json",
                "rates": "inputs/rates.csv" if rates_df is not None else None,
                "dq_mapping": "inputs/dq_mapping.json" if dq_mapping_data is not None else None,
            },
        })

        return RunResponse(
            run_id=run_id, status=RunStatus.completed, created_at=created_at,
            summary=summary, sections=all_sections,
        )

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        run_store.save_manifest(run_id, {
            "status": "failed",
            "run_type": "portfolio",
            "error": error_msg,
            "traceback": traceback.format_exc(),
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


def list_all_runs() -> list[dict[str, Any]]:
    """List all runs from the workspace, sorted by date descending."""
    from ..storage.run_store import _RUNS_DIR
    runs: list[dict[str, Any]] = []
    if not _RUNS_DIR.exists():
        return runs
    for d in _RUNS_DIR.iterdir():
        if not d.is_dir() or not d.name.startswith("run_"):
            continue
        mf = d / "manifest.json"
        if not mf.exists():
            continue
        try:
            import json
            m = json.loads(mf.read_text())
            summary = m.get("summary", {})
            has_inputs = m.get("has_inputs", (d / "inputs").is_dir())
            inferred_run_type = m.get("run_type")
            if not inferred_run_type:
                # Backward-compatibility for older manifests that predate explicit run_type.
                if m.get("deal_id") or m.get("deal_context") or m.get("run_kind") in {"deal_run", "solver"}:
                    inferred_run_type = "structured_deal"
                else:
                    inferred_run_type = "portfolio"
            runs.append({
                "run_id": d.name,
                "status": m.get("status", "unknown"),
                "created_at": m.get("created_at", ""),
                "run_type": inferred_run_type,
                "run_kind": m.get("run_kind"),
                "loan_count": summary.get("loan_count", m.get("loan_count", 0)),
                "group_count": summary.get("group_count", m.get("group_count", 0)),
                "scenario_names": m.get("scenario_names", []),
                "elapsed_seconds": summary.get("elapsed_seconds", m.get("elapsed_seconds")),
                "total_balance": summary.get("total_balance", 0),
                "wac": summary.get("wac", 0),
                "deal_id": m.get("deal_id"),
                "deal_name": m.get("deal_name", m.get("deal_context", {}).get("deal_name")),
                "deal_context": m.get("deal_context", {}),
                "error": m.get("error"),
                "has_inputs": has_inputs,
            })
        except Exception:
            pass
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs


def get_run_config(run_id: str) -> dict[str, Any]:
    """Return the full run config for re-running."""
    manifest = run_store.load_manifest(run_id)
    return {
        "run_config": manifest.get("run_config", {}),
        "scenarios": manifest.get("scenarios", []),
        "group_names": manifest.get("group_names", []),
        "summary": manifest.get("summary", {}),
        "has_inputs": manifest.get("has_inputs", run_store.has_run_inputs(run_id)),
    }


def get_run_input_tape_preview(run_id: str, max_rows: int = 500) -> CashflowPreview:
    """Return the tape that was used for a given run."""
    df = run_store.load_run_input(run_id, "tape")
    truncated = len(df) > max_rows
    total = len(df)
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
        section="input_tape",
        columns=list(df.columns),
        rows=rows,
        row_count=total,
        truncated=truncated,
    )


def get_run_input_assumptions(run_id: str) -> dict[str, Any]:
    """Return the assumptions used for a given run."""
    try:
        return run_store.load_run_input_json(run_id, "assumptions")
    except FileNotFoundError:
        manifest = run_store.load_manifest(run_id)
        return {
            "run_mode": manifest.get("run_config", {}).get("run_mode", "actual"),
            "grouping": manifest.get("run_config", {}).get("grouping"),
            "base_assumptions": manifest.get("scenarios", [{}])[0].get("assumptions", {}),
            "scenarios": manifest.get("scenarios", []),
        }


def get_run_input_mappings(run_id: str) -> dict[str, Any]:
    """Return the column mappings used for a given run."""
    try:
        return run_store.load_run_input_json(run_id, "mappings")
    except FileNotFoundError:
        manifest = run_store.load_manifest(run_id)
        rc = manifest.get("run_config", {})
        return {
            "asof_date": rc.get("asof_date"),
            "mappings": rc.get("mappings", []),
        }


def get_run_groups(run_id: str) -> tuple[list[str], dict[str, str]]:
    manifest = run_store.load_manifest(run_id)
    if manifest.get("run_type") == "structured_deal":
        # Bond/waterfall outputs are not collateral group outputs.
        return [], {}
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
    total_rows = len(df)
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
        row_count=total_rows,
        truncated=truncated,
    )
