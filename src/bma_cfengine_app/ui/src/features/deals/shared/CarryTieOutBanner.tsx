import React, { useState } from "react";
import {
  AlertOctagon,
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Info,
} from "lucide-react";
import type { CarryTieOutResult } from "./carryTieOut";
import { cx } from "../../../components/system/ui";

interface Props {
  /**
   * Pre-computed carry tie-out result. Compute this in the parent
   * (DealEditor / IrPreviewPanel) via `computeStaticCarryTieOut(...)`
   * so the math runs once per render frame and the banner is a pure
   * presentation component.
   */
  result: CarryTieOutResult;
  /**
   * Optional context label rendered above the banner for the
   * IrPreviewPanel surface ("Live tie-out", "Pre-run check", etc.).
   * Defaults to nothing.
   */
  contextLabel?: string;
  /**
   * Optional flag indicating that an engine-truth carry tie-out is
   * available (i.e., a base run has completed). When true, the
   * banner appends a hint that the post-run number is the
   * authoritative one.
   */
  hasPostRunResult?: boolean;
}

/**
 * Carry tie-out banner per `engine_completeness_and_carry_tieout.plan.md`,
 * Phase 5 (guardrail UX). Renders the OK/WARN/BLOCK status of the
 * structure based on the back-solved implied residual yield.
 *
 * Visual contract:
 *
 *   - **OK**: green check + one-line "yield is in the typical band"
 *     copy. The user can run/solve the deal without friction.
 *
 *   - **WARN**: amber triangle + "yield is outside the typical band"
 *     copy with a verb-led suggestion. Run/solve still works but the
 *     banner is sticky to encourage review.
 *
 *   - **BLOCK**: red octagon + "couldn't balance carry" copy. The
 *     parent gates the Run/Solve buttons on this status; the user
 *     must either edit the structure or click an explicit "Override
 *     and run anyway" action (handled in the parent).
 *
 * The "Show details" chevron expands a per-tranche table of coupons,
 * durations, and weights so power users can see *why* the implied
 * yield landed where it did. Most users skim the banner and move on.
 */
export default function CarryTieOutBanner({
  result,
  contextLabel,
  hasPostRunResult,
}: Props) {
  const [showDetails, setShowDetails] = useState(false);

  if (result.is_degenerate) {
    return null;
  }

  const { status, reason } = result;
  const yieldPct = result.implied_residual_yield_convexity_adjusted_pct;
  const tone = TONES[status];

  return (
    <div
      className={cx(
        "rounded-lg border px-3 py-2 text-xs",
        tone.container,
      )}
      role="status"
      aria-live="polite"
    >
      {contextLabel && (
        <div className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">
          {contextLabel}
        </div>
      )}
      <div className="flex items-start gap-2">
        <tone.Icon
          className={cx("w-4 h-4 mt-0.5 shrink-0", tone.icon)}
          aria-hidden
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-baseline gap-2 flex-wrap">
            <span className={cx("font-medium", tone.title)}>
              {tone.headline}
            </span>
            <span className="tabular-nums text-foreground">
              implied residual yield {fmtPct(yieldPct)}
            </span>
          </div>
          <p className="mt-0.5 text-muted-foreground">{reason}</p>
          {hasPostRunResult && (
            <p className="mt-0.5 text-[11px] text-muted-foreground italic flex items-center gap-1">
              <Info className="w-3 h-3" aria-hidden /> Engine-truth carry
              available below — use that to gate the deal.
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={() => setShowDetails((v) => !v)}
          className="text-muted-foreground hover:text-foreground transition-colors text-[11px] inline-flex items-center gap-1"
          aria-expanded={showDetails}
        >
          {showDetails ? (
            <ChevronDown className="w-3 h-3" aria-hidden />
          ) : (
            <ChevronRight className="w-3 h-3" aria-hidden />
          )}
          Details
        </button>
      </div>

      {showDetails && (
        <div className="mt-2 grid grid-cols-2 gap-3 text-[11px]">
          <PoolSummary result={result} />
          <ResidualSummary result={result} />
          {result.tranches.length > 0 && (
            <div className="col-span-2">
              <TrancheTable result={result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ToneStyle {
  container: string;
  Icon: React.ElementType;
  icon: string;
  title: string;
  headline: string;
}

const TONES: Record<CarryTieOutResult["status"], ToneStyle> = {
  OK: {
    container: "border-engine-green/30 bg-engine-green/10",
    Icon: CheckCircle2,
    icon: "text-engine-green",
    title: "text-engine-green",
    headline: "Carry balances —",
  },
  WARN: {
    container: "border-amber-500/30 bg-amber-500/10",
    Icon: AlertTriangle,
    icon: "text-amber-300",
    title: "text-amber-300",
    headline: "Worth a second look —",
  },
  BLOCK: {
    container: "border-destructive/40 bg-destructive/10",
    Icon: AlertOctagon,
    icon: "text-destructive",
    title: "text-destructive",
    headline: "Doesn't balance —",
  },
};

function PoolSummary({ result }: { result: CarryTieOutResult }) {
  return (
    <div className="rounded border border-border/60 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Pool
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 tabular-nums">
        <span className="text-muted-foreground">Net yield</span>
        <span className="text-right">{fmtPct(result.pool_net_yield_pct)}</span>
        <span className="text-muted-foreground">Duration</span>
        <span className="text-right">
          {result.pool_duration_years.toFixed(2)}y
        </span>
        <span className="text-muted-foreground">WAL</span>
        <span className="text-right">
          {result.pool_wal_years.toFixed(2)}y
        </span>
        <span className="text-muted-foreground">Balance</span>
        <span className="text-right">{fmtUsdM(result.pool_balance)}</span>
      </div>
    </div>
  );
}

function ResidualSummary({ result }: { result: CarryTieOutResult }) {
  return (
    <div className="rounded border border-border/60 px-2 py-1.5">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">
        Residual
      </div>
      <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-0.5 tabular-nums">
        <span className="text-muted-foreground">Balance</span>
        <span className="text-right">
          {fmtUsdM(result.residual_balance)}
        </span>
        <span className="text-muted-foreground">Duration</span>
        <span className="text-right">
          {result.residual_duration_years.toFixed(2)}y
        </span>
        <span className="text-muted-foreground" title="Notional weighted yield (context only — ignores time value)">
          Implied (notional)
        </span>
        <span className="text-right">
          {fmtPct(result.implied_residual_yield_notional_pct)}
        </span>
        <span className="text-muted-foreground">Implied (duration)</span>
        <span className="text-right">
          {fmtPct(result.implied_residual_yield_duration_pct)}
        </span>
        <span className="text-muted-foreground font-medium">
          Implied (cvx-adjusted)
        </span>
        <span className="text-right font-medium">
          {fmtPct(result.implied_residual_yield_convexity_adjusted_pct)}
        </span>
      </div>
    </div>
  );
}

function TrancheTable({ result }: { result: CarryTieOutResult }) {
  return (
    <div className="rounded border border-border/60 overflow-hidden">
      <table className="w-full text-[11px]">
        <thead>
          <tr className="bg-grid-header text-muted-foreground">
            <th className="text-left px-2 py-1 font-normal">Class</th>
            <th className="text-right px-2 py-1 font-normal">Notional</th>
            <th className="text-right px-2 py-1 font-normal">Coupon</th>
            <th className="text-right px-2 py-1 font-normal">Duration</th>
            <th className="text-right px-2 py-1 font-normal">Share</th>
          </tr>
        </thead>
        <tbody>
          {result.tranches.map((t) => (
            <tr key={t.name} className="border-t border-border/40">
              <td className="px-2 py-1 text-foreground">{t.name}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {fmtUsdM(t.notional)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {fmtPct(t.coupon_pct)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {t.duration_years.toFixed(2)}y
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {fmtPct(t.weight * 100)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function fmtPct(v: number): string {
  if (!Number.isFinite(v)) return "n/a";
  return `${v.toFixed(2)}%`;
}

function fmtUsdM(v: number): string {
  if (!Number.isFinite(v)) return "—";
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  if (Math.abs(v) >= 1e3) return `$${(v / 1e3).toFixed(0)}K`;
  return `$${v.toFixed(0)}`;
}
